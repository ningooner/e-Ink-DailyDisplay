# PaperDeck — API client
# urequests wrappers for the two endpoints the Pico needs.

import urequests

TIMEOUT = 15  # seconds; /frame is 33 KB so give it a moment


def get_status(api_base):
    """
    GET /status → dict with keys: time, date, weather, spotify.
    spotify keys: is_playing (bool), track_id (str), track, artist, album.
    """
    r = urequests.get(api_base + "/status", timeout=TIMEOUT)
    data = r.json()
    r.close()
    return data


def get_frame_into(api_base, buf):
    """
    GET /frame → stream 33,600 bytes directly into buf (pre-allocated bytearray).

    Zero extra allocation: the response body lands in the caller's buffer in
    chunks via raw.readinto(), so the Pico never holds two 33 KB copies at once.
    """
    import gc
    gc.collect()
    r = urequests.get(api_base + "/frame", timeout=TIMEOUT)
    mv = memoryview(buf)
    total = 0
    while total < len(mv):
        n = r.raw.readinto(mv[total:])
        if not n:
            break
        total += n
    r.close()
