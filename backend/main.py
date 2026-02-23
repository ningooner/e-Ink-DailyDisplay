import datetime
import asyncio
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from weather import fetch_weather
from spotify import get_now_playing, get_stored_art_url, MOCK_MODE
from image_pipeline import get_art_bmp
from renderer import render_idle, render_now_playing, img_to_4gray_buffer

app = FastAPI(title="PaperDeck API")


async def _build_status() -> dict:
    zurich_tz = datetime.timezone(datetime.timedelta(hours=1))
    now = datetime.datetime.now(tz=zurich_tz)
    weather_data, spotify_data = await asyncio.gather(
        fetch_weather(),
        get_now_playing(),
    )
    return {
        "time":    now.strftime("%H:%M"),
        "date":    now.strftime("%a %d %b"),
        "weather": weather_data,
        "spotify": spotify_data,
    }


@app.get("/status")
async def status():
    return await _build_status()


@app.get("/art/{track_id}")
async def album_art(track_id: str):
    """
    Returns a 280×280 4-level greyscale BMP ready for the Pico framebuffer.
    Requires /status to have been called at least once for this track_id
    so the Spotify art URL is in the store. Returns 404 if not found yet.
    """
    from spotify import MOCK_MODE

    art_url_spotify = None

    if MOCK_MODE:
        # No real URL — image_pipeline will generate a gradient
        art_url_spotify = None
    else:
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
    Calling /frame implicitly refreshes Spotify and weather state (same as /status).
    """
    status = await _build_status()
    sp = status["spotify"]

    if sp["is_playing"]:
        art_url = None if MOCK_MODE else get_stored_art_url(sp["track_id"])
        art_bytes = await get_art_bmp(sp["track_id"], art_url)
        img = render_now_playing(status, art_bytes)
    else:
        img = render_idle(status)

    return Response(
        content=img_to_4gray_buffer(img),
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
