# PaperDeck — Pico W firmware entry point
#
# Dual-mode state machine
# ───────────────────────
#   IDLE MODE:   Wi-Fi powered off between polls.  Wake near each minute
#                boundary, connect, fetch /status, update clock/weather,
#                disconnect, sleep.  Low power; no SSE connection.
#
#   ACTIVE MODE: Triggered when /status reports is_playing=True.
#                Wi-Fi stays on.  Open a raw socket to /events (SSE) and
#                react to push events — no polling.  On 'music stopped'
#                event, show idle frame and return to Idle Mode.
#
# Transitions
#   Idle  → Active : /status returns is_playing=True
#   Active → Idle  : SSE pushes spotify_update with is_playing=False

import network
import time
import gc

import config
import api_client
import display


# Seconds of lead time given to Wi-Fi connect + /status HTTP + display
# overhead in idle mode.  We wake this many seconds before the minute
# boundary so the frame hits the screen close to the real minute change.
_IDLE_MARGIN_S = 6


# ── Wi-Fi helpers ─────────────────────────────────────────────────────────────

def wifi_connect(wlan):
    """Bring the radio up and associate.  Safe to call when already connected."""
    wlan.active(True)
    if wlan.isconnected():
        return
    print("Connecting to WiFi:", config.WIFI_SSID)
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    deadline = time.time() + 20
    while not wlan.isconnected():
        if time.time() > deadline:
            raise RuntimeError("WiFi timeout")
        time.sleep(1)
    print("WiFi connected:", wlan.ifconfig()[0])


def wifi_disconnect(wlan):
    """Drop association and power down the radio to save power in idle mode."""
    wlan.disconnect()
    wlan.active(False)


def ensure_wifi(wlan):
    """Reconnect if the link dropped (used in active mode where Wi-Fi must stay on)."""
    if not wlan.isconnected():
        print("WiFi lost — reconnecting")
        wifi_connect(wlan)


# ── Request helpers ───────────────────────────────────────────────────────────

def safe_get_status():
    try:
        return api_client.get_status(config.API_BASE)
    except Exception as e:
        print("get_status error:", e)
        return None


def safe_show():
    try:
        display.show(config.API_BASE)
        return True
    except Exception as e:
        print("show error:", e)
        return False


def _close_sse(sock, sf):
    """Close SSE file wrapper and underlying socket, swallowing any errors."""
    try:
        sf.close()
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass


# ── Idle Mode ─────────────────────────────────────────────────────────────────

def run_idle_mode(wlan, status):
    """
    Idle loop: Wi-Fi is powered off between polls to save energy.

    Each iteration:
      1. Sleep until ~_IDLE_MARGIN_S seconds before the next minute boundary.
      2. Connect to Wi-Fi.
      3. Fetch /status.
      4. If music is playing → return status (Wi-Fi left up for active mode).
      5. Otherwise update the display (partial clock tick or full refresh).
      6. Disconnect Wi-Fi.

    Returns the status dict that triggered the Active Mode entry (is_playing=True).
    Wi-Fi is left connected on return so the caller can immediately show the frame.
    """
    last_track_id = status.get("spotify", {}).get("track_id") if status else None
    last_minute   = status.get("time", "")                     if status else ""
    last_full_s   = time.time()

    while True:
        # Sleep until near the next minute boundary.
        # _IDLE_MARGIN_S accounts for Wi-Fi connect + HTTP + display latency.
        secs    = status.get("seconds", 30) if status else 30
        sleep_s = max(1, min(60 - secs - _IDLE_MARGIN_S, 54))
        print("Idle sleep {}s (server second={})".format(sleep_s, secs))
        time.sleep(sleep_s)

        # Connect
        try:
            wifi_connect(wlan)
        except Exception as e:
            print("Idle WiFi connect failed:", e)
            status = {"seconds": 0}
            continue

        # Fetch status
        status = safe_get_status()
        if status is None:
            wifi_disconnect(wlan)
            time.sleep(10)
            continue

        sp         = status.get("spotify", {})
        is_playing = sp.get("is_playing", False)

        # Music started → hand off to active mode with Wi-Fi already up
        if is_playing:
            print("Music started — entering active mode")
            return status

        # Decide what display update is needed
        track_id      = sp.get("track_id")
        minute        = status.get("time", "")
        force_full    = (time.time() - last_full_s) >= config.FORCE_FULL_INTERVAL_S
        minute_ticked = minute != last_minute
        track_changed = track_id != last_track_id

        if force_full or track_changed:
            safe_show()
            last_full_s = time.time()
        elif minute_ticked:
            # Dynamic delay: target display at second 59 of the current minute.
            # status["seconds"] is the real second when /status was fetched; allow
            # ~1 s for the upcoming get_partial_frame_into() call.
            secs_now = status.get("seconds", 30)
            delay_s  = max(0, 59 - secs_now - 1)
            try:
                display.show_partial(config.API_BASE, delay_s=delay_s)
            except Exception as e:
                print("show_partial error:", e)

        last_minute   = minute
        last_track_id = track_id

        wifi_disconnect(wlan)


# ── Active Mode ───────────────────────────────────────────────────────────────

def run_active_mode(wlan, status):
    """
    Active loop: Wi-Fi stays on; the Pico listens to the /events SSE stream.

    On 'spotify_update' with is_playing=False: show the idle frame, close
    the socket, and return (Wi-Fi left up so the caller can disconnect cleanly).

    On track change or force-full timeout: gc.collect() to defrag the heap,
    fetch the new /frame, then reopen the SSE connection.

    The SSE socket is always closed before a /frame fetch so we never hold a
    live socket and a 33 KB streaming connection simultaneously.
    """
    # Show the initial now-playing frame
    safe_show()

    last_track_id = status.get("spotify", {}).get("track_id")
    last_full_s   = time.time()

    while True:   # SSE reconnect loop
        sock, sf = None, None

        try:
            sock, sf = api_client.open_sse_socket(config.API_BASE)
            print("SSE connected")
        except Exception as e:
            print("SSE connect failed:", e)
            ensure_wifi(wlan)
            time.sleep(3)
            continue

        try:
            while True:   # SSE event loop
                # read_sse_event blocks up to 40 s (keepalive every 30 s).
                # OSError means timeout or link error; check Wi-Fi and decide.
                try:
                    event = api_client.read_sse_event(sf)
                except OSError as e:
                    print("SSE read error:", e)
                    if not wlan.isconnected():
                        break   # link gone → exit inner loop, reconnect
                    continue    # timeout spike (server slow?), keep listening

                if event is None:
                    print("SSE stream closed by server")
                    break       # reconnect outer loop

                etype = event.get("event_type")

                if etype == "connected":
                    continue    # initial handshake frame, ignore

                if etype != "spotify_update":
                    continue    # unknown future event type, ignore

                is_playing = event.get("is_playing", False)
                track_id   = event.get("track_id")

                if not is_playing:
                    # ── Transition: Active → Idle ──────────────────────────
                    # Music stopped.  Show the idle frame while Wi-Fi is still
                    # up, then return.  The finally block closes the socket.
                    print("Music stopped — returning to idle mode")
                    gc.collect()    # free the SSE JSON dict before 33 KB fetch
                    safe_show()     # renders idle frame (Wi-Fi still connected)
                    return

                # ── Track change ───────────────────────────────────────────
                if track_id and track_id != last_track_id:
                    print("Track changed →", track_id)
                    # Close SSE socket before the 33 KB /frame fetch.
                    # This frees the socket's lwIP receive buffer and prevents
                    # the two TCP connections from competing for heap during the
                    # streaming readinto() call.
                    _close_sse(sock, sf)
                    sock, sf = None, None   # prevent double-close in finally
                    gc.collect()            # defrag heap after JSON parse + socket close
                    safe_show()
                    last_track_id = track_id
                    last_full_s   = time.time()
                    break   # reopen SSE after frame fetch

                # ── Force-full periodic refresh ────────────────────────────
                if (time.time() - last_full_s) >= config.FORCE_FULL_INTERVAL_S:
                    print("Force full refresh")
                    _close_sse(sock, sf)
                    sock, sf = None, None
                    gc.collect()
                    safe_show()
                    last_full_s = time.time()
                    break   # reopen SSE after frame fetch

        except Exception as e:
            print("Active SSE loop error:", e)
        finally:
            _close_sse(sock, sf)

        ensure_wifi(wlan)
        time.sleep(2)   # brief pause before reconnecting SSE


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    wlan = network.WLAN(network.STA_IF)
    wifi_connect(wlan)
    display.init()

    # Boot: fetch initial status
    status = None
    while status is None:
        status = safe_get_status()
        if status is None:
            time.sleep(5)

    # Show first frame
    while not safe_show():
        time.sleep(5)

    print("Boot complete")

    # Main dispatch loop
    # run_idle_mode  returns when is_playing=True  (Wi-Fi up)
    # run_active_mode returns when is_playing=False (Wi-Fi up)
    while True:
        if status and status.get("spotify", {}).get("is_playing"):
            run_active_mode(wlan, status)
            # Music stopped; active mode already showed idle frame.
            # Drop Wi-Fi before entering idle sleep.
            wifi_disconnect(wlan)
            status = {"seconds": 30}   # seed idle sleep; updated on first poll
        else:
            status = run_idle_mode(wlan, status)
            # Music started; idle mode returned with Wi-Fi still up.


main()
