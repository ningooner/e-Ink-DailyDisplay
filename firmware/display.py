# PaperDeck — display wrapper
# Thin wrapper around the Waveshare EPD driver (lib/epd_3in7.py).
#
# === ORIENTATION NOTE ===
# The Waveshare driver uses EPD_WIDTH=280, EPD_HEIGHT=480 (portrait scan order).
# Our server renders a 480×280 landscape image, packed row-major.
# The two buffers are the same size (33,600 bytes, GS2_HMSB format) but the
# row width differs: server rows are 480 px wide, driver rows are 280 px wide.
#
# Result: the image will appear rotated 90° on first hardware test.
# Fix: in backend/renderer.py img_to_4gray_buffer(), rotate the PIL image 90°
# before packing (img.rotate(-90, expand=True) turns 480×280 → 280×480).
# The renderer canvas itself does NOT need to change.
#
# === GREY LEVEL ENCODING (confirmed from driver source) ===
# 0x00 = black  0x01 = dark grey  0x02 = light grey  0x03 = white
# This matches what img_to_4gray_buffer() already produces. ✓

import api_client
from epd_3in7 import EPD_3in7  # MicroPython adds /lib/ to sys.path automatically

_epd = None


def init():
    """Initialise the EPD and clear the screen. Call once at boot."""
    global _epd
    _epd = EPD_3in7()
    # EPD_3in7.__init__ already calls EPD_3IN7_4Gray_init() and EPD_3IN7_4Gray_Clear().


def show(api_base):
    """
    Fetch a frame from the server and display it (full 4-gray refresh, ~3 seconds).

    Streams /frame directly into buffer_4Gray via api_client.get_frame_into() —
    no second 33 KB allocation. buffer_4Gray is then passed straight to the driver.
    """
    api_client.get_frame_into(api_base, _epd.buffer_4Gray)
    _epd.EPD_3IN7_4Gray_Display(_epd.buffer_4Gray)


def show_partial(api_base):
    """
    Fetch a 1-gray frame and display via partial refresh (~0.3s, no white flash).

    Used for idle-mode clock-tick updates. Calls EPD_3IN7_1Gray_init() to switch
    the panel into 1-gray mode before sending data (~300ms LUT load included).
    If the server returns 204 (Spotify is playing), this call is a no-op.
    """
    got_frame = api_client.get_partial_frame_into(api_base, _epd.buffer_1Gray)
    if not got_frame:
        return
    _epd.EPD_3IN7_1Gray_init()
    _epd.EPD_3IN7_1Gray_Display_Part(_epd.buffer_1Gray)


def sleep():
    """Put the EPD into deep sleep to save power."""
    _epd.Sleep()
