# PaperDeck — display wrapper
# Thin wrapper around the Waveshare EPD driver (lib/epd_3in7.py).
#
# === ORIENTATION NOTE ===
# The Waveshare driver uses EPD_WIDTH=280, EPD_HEIGHT=480 (portrait scan order).
# Our server renders a 480×280 landscape image, rotated -90° before packing, so
# the wire buffer is 280×480 portrait. This matches the driver's scan order. ✓
#
# === GREY LEVEL ENCODING (confirmed from driver source) ===
# 4-gray: 0x00=black, 0x01=dark grey, 0x02=light grey, 0x03=white (LSB-first packed)
#
# === PARTIAL REFRESH (DU waveform) ===
# EPD_3IN7_1Gray_Display_Part uses the DU (Direct Update) LUT.
# The display controller drives each pixel based on:
#   - 0x26 RAM: what was previously shown (old image)
#   - 0x24 RAM: what we want to show now  (new image)
# If 0x26 doesn't match the physical screen state, pixels don't clear — they stack.
#
# Fix: we maintain _prev_1gray (what's currently on screen as a 1-bit image) and
# write it to 0x26 before each Display_Part call via a single bulk SPI transaction.
# After each update, _prev_1gray is updated with the new frame.
# EPD_3IN7_1Gray_init() is only called once per mode transition (not per tick).

import time

import api_client
from epd_3in7 import EPD_3in7  # MicroPython adds /lib/ to sys.path automatically

_epd = None
_partial_mode = False     # True once 1-gray init has been run; reset by show()
_prev_1gray = None        # Baseline buffer for DU waveform (current screen state)
_screen_has_grey = False  # True after a 4-gray image is on screen; False after any Clear


def init():
    """Initialise the EPD and clear the screen. Call once at boot."""
    global _epd
    _epd = EPD_3in7()
    # EPD_3in7.__init__ already calls EPD_3IN7_4Gray_init() and EPD_3IN7_4Gray_Clear().


def _write_to_0x26(buf):
    """
    Write buf to 0x26 (old-image RAM) for the DU waveform baseline.

    Resets the RAM pointer to (0,0), then streams the full buffer in a single
    SPI transaction — avoids 16,800 individual send_data() call overhead.
    """
    _epd.send_command(0x4E)   # SET_RAM_X_ADDRESS_COUNTER
    _epd.send_data(0x00)
    _epd.send_data(0x00)
    _epd.send_command(0x4F)   # SET_RAM_Y_ADDRESS_COUNTER
    _epd.send_data(0x00)
    _epd.send_data(0x00)
    _epd.send_command(0x26)   # WRITE_RAM (old image)
    _epd.digital_write(_epd.dc_pin, 1)
    _epd.digital_write(_epd.cs_pin, 0)
    _epd.spi.write(buf)
    _epd.digital_write(_epd.cs_pin, 1)


def show(api_base):
    """
    Fetch a frame from the server and display it (full 4-gray refresh, ~6 seconds total).

    Streams /frame directly into buffer_4Gray — no second 33 KB allocation.
    Pre-clears to all-white only when grey pixels are present AND we're transitioning
    from idle/1-bit mode (i.e., the 1Gray_Clear() path was not taken on entry).
    This prevents the 3.5s clear from firing on consecutive music track changes while
    still protecting against grey residuals after unusual state transitions.
    Resets partial-refresh state so the next show_partial() re-initialises 1-gray mode.
    """
    global _partial_mode, _prev_1gray, _screen_has_grey
    api_client.get_frame_into(api_base, _epd.buffer_4Gray)
    if _screen_has_grey and _partial_mode:
        # Grey pixels on screen AND coming from partial/idle mode — clear first.
        # In normal operation this condition is unreachable because _partial_mode is
        # only True after EPD_3IN7_1Gray_Clear() which sets _screen_has_grey=False.
        # Consecutive track changes: _partial_mode=False → skip → saves ~3.5s.
        _epd.EPD_3IN7_4Gray_Clear()
        _screen_has_grey = False
    _epd.EPD_3IN7_4Gray_Display(_epd.buffer_4Gray)
    _screen_has_grey = True  # 4-gray image has grey pixels on screen
    _partial_mode = False
    _prev_1gray = None


def show_partial(api_base, delay_s=15):
    """
    Fetch a 1-gray frame and display via partial refresh (DU waveform, ~0.6s, no flash).

    Used for idle-mode clock-tick updates. On the first call after a full 4-gray
    refresh, runs EPD_3IN7_1Gray_init() once to switch the panel into 1-gray mode
    and seeds the DU baseline with all-white (the screen state after a 4-gray clear).
    Subsequent calls skip the init (~300ms saved) and use the previous frame as the
    exact DU baseline, so only genuinely changed pixels get driven.

    delay_s: seconds to wait after fetching the frame before writing to the display.
    The server pre-renders the next minute's time 20s early; this delay ensures the
    frame hits the screen right at the actual minute boundary rather than too early.

    If the server returns 204 (Spotify is playing), this call is a no-op.
    """
    global _partial_mode, _prev_1gray, _screen_has_grey

    got_frame = api_client.get_partial_frame_into(api_base, _epd.buffer_1Gray)
    if not got_frame:
        return

    if delay_s > 0:
        time.sleep(delay_s)

    if not _partial_mode:
        # First partial refresh after boot or after a full 4-gray display.
        # Switch hardware to 1-gray mode, then do a full 1-gray clear to white.
        # This is critical: the 4-gray display leaves grey pixels on screen, but DU
        # waveform can only drive B/W transitions. Without this clear, grey pixels
        # that should become white are skipped by DU (it thinks they're already white
        # because _prev_1gray is seeded as all-white). The 1Gray_Clear() uses a full
        # waveform (LUT[1]) that properly drives ANY pixel state — including grey — to
        # white, so the all-white seed is actually accurate.
        _epd.EPD_3IN7_1Gray_init()
        _epd.EPD_3IN7_1Gray_Clear()            # drives grey pixels to white (full waveform)
        _screen_has_grey = False               # screen is now pure B&W
        _partial_mode = True
        _prev_1gray = bytearray(b'\xff' * 16800)  # screen is now truly all-white

    # Write previous frame to 0x26 so DU waveform sees correct old/new delta.
    _write_to_0x26(_prev_1gray)

    # Display new frame (writes new image to 0x24 and triggers DU refresh).
    _epd.EPD_3IN7_1Gray_Display_Part(_epd.buffer_1Gray)

    # Commit new frame as baseline for next update.
    _prev_1gray[:] = _epd.buffer_1Gray


def sleep():
    """Put the EPD into deep sleep to save power."""
    _epd.Sleep()
