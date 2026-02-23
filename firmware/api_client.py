# PaperDeck — API client
# HTTP helpers for the two frame endpoints (urequests) and the SSE event
# stream (raw socket).  All large buffers are pre-allocated by the caller.

import socket
import ujson
import urequests

TIMEOUT = 15  # seconds; /frame is 33 KB so give it a moment


# ── Existing HTTP helpers (unchanged) ─────────────────────────────────────

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
    Raises OSError if fewer than len(buf) bytes are received (partial read guard).
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
    if total != len(buf):
        raise OSError("frame truncated: got {} of {} bytes".format(total, len(buf)))


def get_partial_frame_into(api_base, buf):
    """
    GET /frame_partial → stream 16,800 bytes into buf (epd.buffer_1Gray).

    Returns True if a frame was received and loaded into buf.
    Returns False if the server responded 204 (Spotify is playing — skip partial update).
    Raises OSError if the byte count doesn't match (partial read guard).
    """
    import gc
    gc.collect()
    r = urequests.get(api_base + "/frame_partial", timeout=TIMEOUT)
    if r.status_code == 204:
        r.close()
        return False
    if r.status_code != 200:
        r.close()
        raise OSError("/frame_partial returned HTTP {}".format(r.status_code))
    mv = memoryview(buf)
    total = 0
    while total < len(mv):
        n = r.raw.readinto(mv[total:])
        if not n:
            break
        total += n
    r.close()
    if total != len(buf):
        raise OSError("partial frame truncated: got {} of {} bytes".format(total, len(buf)))
    return True


# ── SSE socket helpers ─────────────────────────────────────────────────────
#
# Memory strategy
# ───────────────
# urequests is not used for SSE because it buffers the entire response body,
# which would block indefinitely on a streaming endpoint.  Instead we open a
# raw socket, write the HTTP request manually, then wrap the socket in a
# makefile('rb') file-like object that gives us a readline() that allocates
# only one line at a time (~100 bytes worst case).
#
# The socket + its internal receive buffer (~a few KB in lwIP) lives for the
# duration of the active mode session.  It is closed explicitly before any
# call to get_frame_into() so the 33 KB frame stream has maximum contiguous
# heap available (even though buffer_4Gray is pre-allocated, the lwIP socket
# buffers would add fragmentation pressure).
#
# HTTP/1.0 is requested to avoid chunked transfer encoding.  If the server
# responds with HTTP/1.1 chunked anyway, read_sse_event() silently skips
# chunk-size lines (pure hex strings) before parsing data lines.


def _parse_host_port(api_base):
    """Parse 'http://host:port' → (host_str, port_int)."""
    url = api_base
    if url.startswith("http://"):
        url = url[7:]
    if "/" in url:
        url = url[:url.index("/")]
    if ":" in url:
        host, port_s = url.rsplit(":", 1)
        return host, int(port_s)
    return url, 80


def open_sse_socket(api_base):
    """
    Open a raw TCP socket to /events and skip the HTTP response headers.

    Uses HTTP/1.0 to suppress chunked transfer encoding (SSE is a plain line
    stream with no framing overhead).  Sets a 40 s socket timeout — the server
    sends a keepalive comment every 30 s, so a timeout means the connection
    truly dropped.

    Returns (sock, sf) where sf is a makefile('rb') wrapper supporting
    readline().  The caller must close both sf and sock when done.
    Raises OSError / RuntimeError on connect or header-parse failure.
    """
    host, port = _parse_host_port(api_base)
    addr = socket.getaddrinfo(host, port)[0][-1]

    sock = socket.socket()
    sock.settimeout(40)        # 30 s keepalive + 10 s margin before declaring dead
    sock.connect(addr)

    req = (
        "GET /events HTTP/1.0\r\n"
        "Host: {host}:{port}\r\n"
        "Accept: text/event-stream\r\n"
        "Cache-Control: no-cache\r\n"
        "\r\n"
    ).format(host=host, port=port)
    sock.send(req.encode())

    sf = sock.makefile('rb')

    # Consume HTTP response headers (read until blank line)
    while True:
        line = sf.readline()
        if not line:
            raise RuntimeError("SSE: connection closed before headers finished")
        if line in (b'\r\n', b'\n'):
            break   # blank line = end of headers

    return sock, sf


def read_sse_event(sf):
    """
    Read one SSE data line from an open makefile stream.

    Returns a dict if a 'data: {...}' line was parsed.
    Returns None if the connection was closed cleanly (EOF).
    Raises OSError on socket timeout or low-level network error — the caller
    should check wlan.isconnected() and decide whether to reconnect.

    Transparently handles:
    - HTTP/1.1 chunked framing: pure-hex size lines are skipped.
    - SSE comments (': ...') and blank event-delimiter lines: skipped.
    - Malformed JSON: returns an empty dict so the caller loop continues.
    """
    while True:
        line = sf.readline()     # blocks up to sock.settimeout() seconds

        if not line:             # b'' → EOF, connection closed
            return None

        line = line.decode('utf-8').rstrip('\r\n')

        # Skip HTTP/1.1 chunked-encoding size markers (pure hex strings)
        if line and all(c in '0123456789abcdefABCDEF' for c in line):
            continue

        # Skip SSE comments and blank event-delimiter lines
        if not line or line.startswith(':'):
            continue

        if line.startswith('data: '):
            try:
                return ujson.loads(line[6:])
            except Exception:
                return {}   # malformed JSON: return empty dict, caller will skip
