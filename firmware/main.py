# PaperDeck — Pico W firmware entry point
#
# State machine:
#   Boot → connect WiFi → init display → fetch & show first frame
#   Loop every POLL_INTERVAL_S:
#     poll /status
#     if anything changed → fetch /frame → refresh display
#
# "Changed" means:
#   - Spotify mode flipped (idle ↔ now-playing)
#   - Track ID changed while playing
#   - Clock minute ticked (idle screen only — now-playing has no clock)
#   - FORCE_FULL_INTERVAL_S elapsed (clear accumulated ghosting)

import network
import time

import config
import api_client
import display


# ── Wi-Fi ─────────────────────────────────────────────────────────────────────

def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan

    print("Connecting to WiFi:", config.WIFI_SSID)
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)

    deadline = time.time() + 20
    while not wlan.isconnected():
        if time.time() > deadline:
            raise RuntimeError("WiFi timeout")
        time.sleep(1)

    print("WiFi connected:", wlan.ifconfig()[0])
    return wlan


def ensure_wifi(wlan):
    """Reconnect if the link dropped."""
    if not wlan.isconnected():
        print("WiFi lost — reconnecting")
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        deadline = time.time() + 20
        while not wlan.isconnected():
            if time.time() > deadline:
                raise RuntimeError("WiFi reconnect timeout")
            time.sleep(1)
        print("WiFi reconnected")


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _smart_sleep(status):
    """
    Sleep until ~1s before the next minute boundary, capped at POLL_INTERVAL_S.

    Uses the server's 'seconds' field from the last /status response to schedule
    the next poll so the Pico wakes up just before each minute tick rather than
    sleeping a fixed interval. This keeps the displayed clock within ~2-3s of
    real time regardless of boot timing.
    """
    secs = status.get("seconds", 30) if status else config.POLL_INTERVAL_S
    sleep_s = max(1, min(60 - secs - 1, config.POLL_INTERVAL_S))
    time.sleep(sleep_s)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Boot: connect WiFi, init display, show first frame
    wlan = wifi_connect()
    display.init()

    status = None
    while status is None:
        status = safe_get_status()
        if status is None:
            time.sleep(5)

    while not safe_show():
        time.sleep(5)

    # Snapshot of what's on screen
    sp = status.get("spotify", {})
    last_is_playing = sp.get("is_playing", False)
    last_track_id   = sp.get("track_id", "")
    last_minute     = status.get("time", "")
    last_full_s     = time.time()

    print("Boot complete. Polling every", config.POLL_INTERVAL_S, "s max")

    # Loop — sleep is now dynamic (see _smart_sleep) rather than a fixed interval
    while True:
        ensure_wifi(wlan)

        status = safe_get_status()
        if status is None:
            time.sleep(config.POLL_INTERVAL_S)
            continue

        sp          = status.get("spotify", {})
        is_playing  = sp.get("is_playing", False)
        track_id    = sp.get("track_id", "")
        minute      = status.get("time", "")

        mode_changed  = is_playing != last_is_playing
        track_changed = is_playing and (track_id != last_track_id)
        minute_ticked = (not is_playing) and (minute != last_minute)
        force_full    = (time.time() - last_full_s) >= config.FORCE_FULL_INTERVAL_S

        if not (mode_changed or track_changed or minute_ticked or force_full):
            _smart_sleep(status)
            continue

        # Something changed — fetch and show the new frame
        reason = ("mode" if mode_changed else
                  "track" if track_changed else
                  "force" if force_full else "minute")
        print("Refreshing display ({})".format(reason))

        if minute_ticked and not mode_changed and not track_changed and not force_full:
            # Clock tick only: use partial refresh (~0.6s total, no white flash)
            try:
                display.show_partial(config.API_BASE)
            except Exception as e:
                print("show_partial error:", e)
                _smart_sleep(status)
                continue
        else:
            if not safe_show():
                _smart_sleep(status)
                continue

        if mode_changed or track_changed or force_full:
            last_full_s = time.time()

        last_is_playing = is_playing
        last_track_id   = track_id
        last_minute     = minute
        _smart_sleep(status)


main()
