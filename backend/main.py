import datetime
import asyncio
import json
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse

from weather import fetch_weather
from spotify import get_now_playing, get_stored_art_url, MOCK_MODE
from image_pipeline import get_art_bmp
from renderer import render_idle, render_now_playing, img_to_4gray_buffer, img_to_1gray_buffer


# ── Persistent Spotify state (owned by background poller) ─────────────────
# Replaced the old TTL cache (_spotify_cache / _get_cached_spotify).
# The poller keeps this up-to-date at 1.5 s cadence; /status reads it
# directly with zero API overhead.
_spotify_state: dict = {
    "is_playing": False,
    "track":      None,
    "artist":     None,
    "album":      None,
    "track_id":   None,
    "art_url":    None,
}


# ── SSE subscriber registry ────────────────────────────────────────────────
# Each connected /events client gets one asyncio.Queue (maxsize=32).
# The poller calls _broadcast_sse(); the StreamingResponse generator drains it.
_sse_subscribers: set[asyncio.Queue] = set()


def _broadcast_sse(event: dict) -> None:
    """Push a JSON event into every active SSE subscriber queue."""
    payload = json.dumps(event)
    dead: set[asyncio.Queue] = set()
    for q in _sse_subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.add(q)
    _sse_subscribers -= dead


# ── Pre-rendered 4-gray frame cache ────────────────────────────────────────
_frame_cache: dict[str, bytes] = {}  # track_id → 33,600 packed 2bpp bytes


async def _prerender_frame(track_id: str, status: dict, art_url: str | None) -> None:
    """Background task: render the now-playing frame and store in _frame_cache."""
    try:
        art_bytes = await get_art_bmp(track_id, art_url)
        img = render_now_playing(status, art_bytes)
        _frame_cache[track_id] = img_to_4gray_buffer(img)
        print(f"[prerender] cached frame for {track_id}")
    except Exception as exc:
        print(f"[prerender] failed for {track_id}: {exc}")


# ── Background Spotify polling loop ────────────────────────────────────────
_SPOTIFY_POLL_INTERVAL = 1.5  # seconds


async def _spotify_poll_loop() -> None:
    """
    Runs from app startup to shutdown. Polls Spotify every 1.5 s, maintains
    _spotify_state, triggers pre-rendering on track change, and broadcasts SSE
    events whenever play-state or track changes.
    """
    global _spotify_state
    print("[poller] started")
    while True:
        try:
            new_state = await get_now_playing()
            old_state = _spotify_state

            track_changed      = new_state.get("track_id") != old_state.get("track_id")
            playstate_changed  = new_state.get("is_playing") != old_state.get("is_playing")

            _spotify_state = new_state  # always advance the cache

            if track_changed or playstate_changed:
                print(
                    f"[poller] state change → "
                    f"track_id={new_state.get('track_id')!r} "
                    f"is_playing={new_state.get('is_playing')}"
                )
                _broadcast_sse({
                    "event_type": "spotify_update",
                    "is_playing": new_state.get("is_playing"),
                    "track_id":   new_state.get("track_id"),
                    "track":      new_state.get("track"),
                    "artist":     new_state.get("artist"),
                    "album":      new_state.get("album"),
                    "art_url":    new_state.get("art_url"),
                })

                # Pre-render the now-playing frame when a new track starts.
                # render_now_playing only needs status["spotify"] and status["time"],
                # so we build a lightweight dict rather than a full _build_status() call.
                if track_changed and new_state.get("is_playing") and new_state.get("track_id"):
                    tid = new_state["track_id"]
                    if tid not in _frame_cache:
                        zurich_tz  = datetime.timezone(datetime.timedelta(hours=1))
                        now        = datetime.datetime.now(tz=zurich_tz)
                        display_now = now + datetime.timedelta(minutes=1) if now.second >= 40 else now
                        minimal_status = {
                            "time":    display_now.strftime("%H:%M"),
                            "spotify": new_state,
                        }
                        cdn_url = None if MOCK_MODE else get_stored_art_url(tid)
                        asyncio.create_task(_prerender_frame(tid, minimal_status, cdn_url))

        except Exception as exc:
            print(f"[poller] error: {exc}")

        await asyncio.sleep(_SPOTIFY_POLL_INTERVAL)


# ── App lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_spotify_poll_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="PaperDeck API", lifespan=lifespan)


# ── Status builder ──────────────────────────────────────────────────────────
async def _build_status() -> dict:
    zurich_tz = datetime.timezone(datetime.timedelta(hours=1))
    now = datetime.datetime.now(tz=zurich_tz)
    display_now = now + datetime.timedelta(minutes=1) if now.second >= 40 else now

    # Weather still fetched here; it has its own cache inside fetch_weather().
    # Spotify comes straight from _spotify_state — no live API call needed.
    weather_data = await fetch_weather()

    return {
        "time":    display_now.strftime("%H:%M"),
        "seconds": now.second,
        "date":    display_now.strftime("%a %d %b"),
        "weather": weather_data,
        "spotify": _spotify_state,
    }


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/status")
async def status():
    return await _build_status()


@app.get("/events")
async def events():
    """
    Server-Sent Events stream.  Subscribe here to receive push notifications
    without polling.  The stream is designed to be extensible: route any future
    server-originated notifications (weather alerts, system events, etc.) through
    this same endpoint by adding new event_type values.

    Event payload shape:
        data: {"event_type": "spotify_update", "is_playing": bool,
               "track_id": str|null, "track": str|null, ...}

    The stream sends an initial {"event_type": "connected"} frame on connect,
    then a ": keepalive" comment every 30 s to prevent proxy timeouts.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=32)
    _sse_subscribers.add(queue)

    async def generator():
        try:
            # Immediate confirmation so the client knows the stream is live.
            yield 'data: {"event_type": "connected"}\n\n'
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # SSE comment — keeps the TCP connection alive through proxies.
                    yield ": keepalive\n\n"
        finally:
            _sse_subscribers.discard(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx response buffering for SSE
        },
    )


@app.get("/art/{track_id}")
async def album_art(track_id: str):
    """
    Returns a 280×280 4-level greyscale BMP ready for the Pico framebuffer.
    Requires /status to have been called at least once for this track_id
    so the Spotify art URL is in the store.  Returns 404 if not found yet.
    """
    art_url_spotify = None

    if not MOCK_MODE:
        art_url_spotify = get_stored_art_url(track_id)
        if not art_url_spotify:
            raise HTTPException(
                status_code=404,
                detail=f"No art URL found for track_id '{track_id}'. "
                       f"Call /status first to populate the store."
            )

    try:
        bmp_bytes = await get_art_bmp(track_id, art_url_spotify)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch art: {e}")

    return Response(
        content=bmp_bytes,
        media_type="image/bmp",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/frame")
async def frame():
    """
    Returns a packed 2bpp binary frame (33,600 bytes) ready to write directly
    to the Waveshare Pico-ePaper-3.7 framebuffer.

    Renders now-playing if Spotify is active, otherwise renders the idle screen.
    Serves a pre-rendered frame from _frame_cache on cache hit (instant),
    falls back to live rendering if the background task hasn't finished yet.
    """
    status = await _build_status()
    sp = status["spotify"]

    if sp["is_playing"]:
        tid = sp["track_id"]
        if tid in _frame_cache:
            return Response(
                content=_frame_cache[tid],
                media_type="application/octet-stream",
                headers={"Cache-Control": "no-store", "Content-Length": "33600"},
            )
        # Cache miss: pre-render not done yet — render live as fallback.
        art_url = None if MOCK_MODE else get_stored_art_url(tid)
        art_bytes = await get_art_bmp(tid, art_url)
        img = render_now_playing(status, art_bytes)
    else:
        img = render_idle(status)

    return Response(
        content=img_to_4gray_buffer(img),
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store", "Content-Length": "33600"},
    )


@app.get("/frame_partial")
async def frame_partial():
    """
    Returns a packed 1bpp binary frame (16,800 bytes) for EPD_3IN7_1Gray_Display_Part.
    Used for idle-mode clock-tick updates (~0.3 s partial refresh, no white flash).
    Returns HTTP 204 if Spotify is currently playing — caller should skip the update.
    """
    status = await _build_status()
    if status["spotify"]["is_playing"]:
        return Response(status_code=204)
    img = render_idle(status)
    return Response(
        content=img_to_1gray_buffer(img),
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store", "Content-Length": "16800"},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
