# PaperDeck — Firmware

> MicroPython firmware for the Raspberry Pi Pico WH + Waveshare Pico-ePaper-3.7.
>
> Status: **not yet written** — hardware arrived February 2026. Backend is live and ready.

---

## Planned File Structure

```
firmware/
├── main.py         ← Entry point + state machine (boot → loop)
├── config.py       ← Wi-Fi credentials, API base URL, timezone offset
├── display.py      ← E-ink full/partial refresh helpers
├── api_client.py   ← urequests wrapper for /status and /art/
└── lib/
    └── epd_3in7.py ← Waveshare EPD driver (MicroPython)
```

---

## Step 0: Flash MicroPython

Before any of this code can run, MicroPython must be on the device:

1. Download the **Pico W** `.uf2` from [micropython.org/download/RPI_PICO_W](https://micropython.org/download/RPI_PICO_W/)
2. Hold **BOOTSEL** on the Pico while plugging it into USB — it appears as `RPI-RP2` drive
3. Drag and drop the `.uf2` onto the drive — it reboots into MicroPython automatically

Connect via serial (e.g. `screen /dev/tty.usbmodem* 115200` on Mac, or use Thonny) to get a REPL.

---

## Step 1: Install the Waveshare EPD Driver

The Waveshare Pico-ePaper-3.7 comes with a MicroPython library. Get `epd_3in7.py` from the [Waveshare wiki](https://www.waveshare.com/wiki/Pico-ePaper-3.7) or the official GitHub repo, and copy it to `firmware/lib/epd_3in7.py`. Then upload it to the Pico at `/lib/epd_3in7.py`.

---

## Step 2: Configure

Create `firmware/config.py`:

```python
WIFI_SSID     = "YourNetwork"
WIFI_PASSWORD = "YourPassword"
API_BASE      = "http://192.168.1.220:8765"   # cribbbserver LAN IP
POLL_INTERVAL_S   = 5
TIMEZONE_OFFSET_H = 1                          # UTC+1 for CET (update for CEST)
```

> Use the LAN IP (`192.168.1.220`) when on the home network. The Tailscale IP (`100.84.37.35`) also works if Tailscale is running on the Pico — but that's not planned for the initial build.

---

## State Machine

```
BOOT
  │
  ├─ Connect Wi-Fi
  ├─ Sync NTP
  ├─ Fetch /status
  └─ Render IDLE screen (full refresh)
        │
        ▼
     LOOP (every 5s)
        │
        ├─ Poll /status
        │
        ├─ [spotify.is_playing = true]
        │     ├─ track changed? → fetch /art/{id} → FULL refresh
        │     └─ same track?   → partial refresh
        │
        └─ [spotify.is_playing = false]
              ├─ clock minute changed? → partial refresh (time)
              └─ weather stale?        → partial refresh (weather block)

Every ~60 minutes: force full refresh to clear greyscale ghosting
```

---

## Refresh Strategy

| Event | Type | Duration |
|---|---|---|
| Boot / mode switch | Full | ~3s (white flash) |
| New track | Full | ~3s |
| Clock minute tick | Partial | ~0.3s |
| Weather update | Partial | ~0.3s |

---

## Hardware Wiring

The Waveshare Pico-ePaper-3.7 plugs directly onto the Pico WH's 40-pin header — no wiring needed. SPI pins used:

| E-Ink Pin | Pico GPIO |
|---|---|
| DIN (MOSI) | GP11 |
| CLK (SCLK) | GP10 |
| CS | GP9 |
| DC | GP8 |
| RST | GP12 |
| BUSY | GP13 |

---

## Dependencies

| Library | Source |
|---|---|
| `epd_3in7.py` | Waveshare wiki / GitHub |
| `network` | MicroPython built-in |
| `urequests` | MicroPython built-in |
| `ntptime` | MicroPython built-in |
| `framebuf` | MicroPython built-in |

---

## How to Deploy Files to the Pico

Use [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) or [Thonny](https://thonny.org/):

```bash
# Install mpremote
pip install mpremote

# Copy all firmware files
mpremote cp firmware/config.py :config.py
mpremote cp firmware/main.py :main.py
mpremote cp firmware/display.py :display.py
mpremote cp firmware/api_client.py :api_client.py
mpremote mkdir :lib
mpremote cp firmware/lib/epd_3in7.py :lib/epd_3in7.py

# Run interactively to test
mpremote run firmware/main.py

# Or soft-reset to run main.py from flash
mpremote reset
```

---

## Build Order (Phase 4)

- [ ] Flash MicroPython onto Pico WH
- [ ] Copy Waveshare EPD driver to `firmware/lib/epd_3in7.py`
- [ ] Write `config.py` with Wi-Fi creds and `API_BASE`
- [ ] Write `api_client.py` — `urequests` wrapper for `/status` and `/art/`
- [ ] Write `display.py` — full and partial refresh helpers wrapping EPD driver
- [ ] Write `main.py` — full state machine
- [ ] End-to-end test: play Spotify → display updates
