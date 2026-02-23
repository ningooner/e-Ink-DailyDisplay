# Pico E-Ink Smart Display — PaperDeck

> A portable, battery-powered smart display built on a Raspberry Pi Pico WH that shows weather forecasts and time when idle, and switches to Spotify album art + track info when music is playing.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Hardware](#hardware)
3. [System Architecture](#system-architecture)
4. [Tech Stack](#tech-stack)
5. [API & Data Pipeline](#api--data-pipeline)
6. [Docker Backend](#docker-backend)
7. [Pico Firmware](#pico-firmware)
8. [Display Logic & State Machine](#display-logic--state-machine)
9. [Album Art Pipeline](#album-art-pipeline)
10. [Power & Battery](#power--battery)
11. [Project Phases](#project-phases)
12. [Folder Structure](#folder-structure)
13. [Open Questions / Future Ideas](#open-questions--future-ideas)

---

## Project Overview

**Name:** Pico E-Ink Smart Display (working title: *PaperDeck*)

**Type:** Portable embedded display gadget

**Summary:**
A palm-sized, e-ink display badge that lives on your desk or in your pocket. It connects to your home Wi-Fi and talks to a lightweight Docker backend running on a home server. In idle mode it shows the current time, date, and a 6-hour weather forecast with a rotating photo from a personal gallery. The moment you start playing music on Spotify, it detects the change and switches to show the album art (dithered to 4-level greyscale), track name, and artist — updating with each track change.

**Key design principles:**
- Pico stays as **dumb as possible** — all heavy lifting (OAuth, image processing, API calls) happens on the server
- **Low power** — e-ink display draws near-zero current when not refreshing; Wi-Fi can be duty-cycled
- **Fully local** — all traffic stays on the home network; no cloud dependency beyond the upstream APIs themselves
- **Modular** — the backend API is generic enough to serve other display clients in future

---

## Hardware

### Core Components

| Component | Model | Key Specs |
|---|---|---|
| Microcontroller | Raspberry Pi Pico WH | RP2040, dual-core 133MHz, 264KB SRAM, 2MB Flash, Wi-Fi 802.11n, pre-soldered headers |
| Display | Waveshare Pico-ePaper-3.7 (WS-20123) | 480×280px, SPI, 4-level greyscale, 3s full refresh, 0.3s partial refresh, 3.3V |
| Battery | 800mAh LiPo | ~8–9h estimated runtime at typical load |
| Power Management | Pimoroni LiPo SHIM or Adafruit PowerBoost 500C | LiPo charging + 3.3V/5V boost for Pico |

### Wiring (SPI — Pico WH to Pico-ePaper-3.7)

The Waveshare Pico-ePaper-3.7 is designed to plug directly onto the Pico WH headers — no wiring required. It uses the following GPIO pins via SPI:

| E-Ink Pin | Pico GPIO | Function |
|---|---|---|
| VCC | 3V3 | Power |
| GND | GND | Ground |
| DIN (MOSI) | GP11 | SPI data |
| CLK (SCLK) | GP10 | SPI clock |
| CS | GP9 | Chip select |
| DC | GP8 | Data/Command |
| RST | GP12 | Reset |
| BUSY | GP13 | Busy signal |

> The display module plugs directly onto the Pico's 40-pin header — it's a hat-style form factor.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   EXTERNAL SERVICES                      │
│                                                         │
│  [Spotify Web API]     [Open-Meteo API]    [NTP Server] │
└───────┬────────────────────┬───────────────────┬────────┘
        │                    │                   │
        ▼                    ▼                   ▼
┌─────────────────────────────────────────────────────────┐
│              DOCKER BACKEND (Home Server)                │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │           FastAPI  (pico-display-api)            │   │
│  │                                                  │   │
│  │  /status        → unified JSON (weather +        │   │
│  │                   time + now-playing)            │   │
│  │  /art/{id}      → pre-processed greyscale BMP   │   │
│  │                                                  │   │
│  │  Internal:                                       │   │
│  │  - Spotify OAuth token refresh loop             │   │
│  │  - Weather cache (15 min TTL)                   │   │
│  │  - Pillow image processing pipeline             │   │
│  └─────────────────────────────────────────────────┘   │
└───────────────────────────┬─────────────────────────────┘
                            │  Local Wi-Fi (HTTP/JSON)
                            │
┌───────────────────────────▼─────────────────────────────┐
│                  RASPBERRY PI PICO WH                    │
│                  (MicroPython firmware)                  │
│                                                         │
│  - Polls /status every 5–10s                           │
│  - Fetches /art/{id} on track change                   │
│  - Manages full vs. partial e-ink refresh              │
│  - Duty-cycles Wi-Fi to save power                     │
└───────────────────────────┬─────────────────────────────┘
                            │  SPI
                            ▼
              ┌─────────────────────────┐
              │  Waveshare Pico-ePaper  │
              │  3.7" 480×280 E-Ink     │
              └─────────────────────────┘
```

---

## Tech Stack

### Backend (Docker, Home Server)

| Layer | Technology | Purpose |
|---|---|---|
| Runtime | Python 3.11 | Backend language |
| Framework | FastAPI | Lightweight async API server |
| Image processing | Pillow (PIL) + NumPy | Resize, greyscale, dither album art and photos |
| HTTP client | httpx | Async calls to Spotify + Open-Meteo |
| Auth | Spotipy or manual OAuth2 | Spotify token management |
| Containerisation | Docker + Docker Compose | Deployment on home server |
| Caching | In-memory dict (or Redis if scaling) | Weather + token cache |
| Networking | Local LAN (+ optional Tailscale) | Pico ↔ server comms |

### Firmware (Pico WH)

| Layer | Technology | Purpose |
|---|---|---|
| Language | MicroPython | Pico firmware |
| Display driver | Waveshare EPD_3in7 MicroPython lib | E-ink rendering |
| Networking | `network` + `urequests` | Wi-Fi + HTTP |
| Time | `ntptime` | Clock sync |
| Image rendering | `framebuf` | Bitmap buffer to display |

---

## API & Data Pipeline

### Spotify Web API

- **Endpoint used:** `GET /v1/me/player/currently-playing`
- **Auth:** OAuth2 with Authorization Code Flow
  - Initial auth done **once** on a PC/browser
  - Refresh token stored in backend `.env`
  - Backend handles all token refreshing automatically
  - Pico never touches OAuth — it just calls `/status` on the local API
- **Poll interval:** Every 5–10 seconds (within Spotify's rate limits)
- **Data extracted:** Track name, artist, album name, album art URL, is_playing flag

### Open-Meteo (Weather)

- **Free, no API key required**
- **Endpoint:** `https://api.open-meteo.com/v1/forecast`
- **Parameters:** Latitude/longitude (hardcoded for home location), hourly temperature, weather code, precipitation probability
- **Poll interval:** Every 15 minutes, cached server-side
- **Data extracted:** Current temp, condition code, 6-hour forecast (hour label + temp + condition per slot)

### NTP Time

- Synced on Pico boot via `ntptime.settime()`
- Re-synced every hour
- Timezone offset applied in firmware config

---

## Docker Backend

### Services (`docker-compose.yml`)

```yaml
services:
  pico-api:
    build: ./backend
    ports:
      - "8765:8765"
    env_file: .env
    restart: unless-stopped
```

### Environment Variables (`.env`)

```env
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REFRESH_TOKEN=your_refresh_token
HOME_LAT=51.5074
HOME_LON=-0.1278
WEATHER_CACHE_TTL=900
```

### Key API Endpoints

#### `GET /status`

Returns a unified JSON payload — the Pico's single source of truth.

```json
{
  "time": "14:32",
  "date": "Thu 19 Feb",
  "weather": {
    "temp_c": 12,
    "condition": "partly_cloudy",
    "forecast": [
      { "hour": "15:00", "temp_c": 11, "condition": "partly_cloudy" },
      { "hour": "19:00", "temp_c": 9,  "condition": "overcast" },
      { "hour": "23:00", "temp_c": 7,  "condition": "rain" },
      { "hour": "03:00", "temp_c": 6,  "condition": "rain" },
      { "hour": "07:00", "temp_c": 8,  "condition": "drizzle" },
      { "hour": "11:00", "temp_c": 12, "condition": "sunny" }
    ]
  },
  "spotify": {
    "is_playing": true,
    "track": "Pyramid Song",
    "artist": "Radiohead",
    "album": "Amnesiac",
    "track_id": "abc123",
    "art_url": "/art/abc123"
  }
}
```

#### `GET /art/{track_id}`

Returns a pre-processed BMP: resized to 280×280, converted to 4-level greyscale with Floyd-Steinberg dithering. Ready for direct framebuffer push to the e-ink display.

---

## Pico Firmware

### State Machine

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
        ├─ [Spotify is_playing = true]
        │     ├─ track changed? → fetch /art/{id} → FULL refresh
        │     └─ same track?   → partial refresh (progress / title)
        │
        └─ [Spotify is_playing = false]
              ├─ clock minute changed? → partial refresh (time)
              └─ weather stale?        → partial refresh (weather block)
```

### Refresh Strategy

| Event | Refresh Type | Duration |
|---|---|---|
| Boot / mode switch | Full refresh | 3s (with white flash) |
| New track | Full refresh | 3s |
| Clock minute tick | Partial refresh | 0.3s |
| Same track (progress) | Partial refresh | 0.3s |
| Weather update | Partial refresh | 0.3s |

> Full refresh every ~60 minutes regardless, to clear greyscale ghosting.

### Config (`config.py` on Pico)

```python
WIFI_SSID = "YourNetwork"
WIFI_PASSWORD = "YourPassword"
API_BASE = "http://192.168.1.x:8765"
POLL_INTERVAL_S = 5
TIMEZONE_OFFSET_H = 1  # UTC+1 for CET
```

---

## Album Art Pipeline

Handled entirely server-side:

```
Spotify API
    │
    │  album art JPEG URL (typically 640×640)
    ▼
Backend (Pillow + NumPy)
    ├─ 1. Download JPEG
    ├─ 2. Resize to 280×280 (fit within display height)
    ├─ 3. Convert to greyscale (mode 'L')
    ├─ 4. Apply Floyd-Steinberg dithering → 4 levels (0, 85, 170, 255)
    ├─ 5. Save as raw BMP (Pico framebuf compatible)
    └─ 6. Cache by track_id (invalidated on new track)
            │
            ▼
         Pico fetches BMP → pushes to framebuf → renders
```

---

## Power & Battery

| Component | Current Draw | Notes |
|---|---|---|
| Pico WH (Wi-Fi active) | ~80mA | During polling |
| Pico WH (Wi-Fi dormant) | ~20mA | Between polls |
| E-ink during refresh | ~8mA | Only during 3s/0.3s refresh window |
| E-ink standby | <0.01µA | Near zero — e-ink holds image with no power |
| LiPo module quiescent | ~5mA | Charging/boost overhead |

**Estimated runtime on 800mAh:**
- Continuous Wi-Fi active: ~8–9 hours
- With Wi-Fi duty cycling (sleep between polls): 12–15+ hours

**Power optimisation ideas (later phases):**
- Use `machine.lightsleep()` on Pico between polls
- Only wake Wi-Fi when needed, sleep immediately after
- Longer poll interval when in idle/weather mode (60s vs 5s)

---

## Project Phases

### Phase 0 — Documentation & Planning
- [x] Define architecture
- [x] Document tech stack
- [x] Set up project repo structure

### Phase 1 — Backend Foundation
- [ ] Scaffold FastAPI app in Docker
- [ ] Implement `/status` endpoint with mocked Spotify data
- [ ] Integrate Open-Meteo weather fetching
- [ ] Test endpoint responses with `curl` / browser

### Phase 2 — Spotify Integration
- [ ] Set up Spotify Developer App (client ID + secret)
- [ ] Complete OAuth flow on PC, obtain refresh token
- [ ] Implement token refresh loop in backend
- [ ] Implement `/v1/me/player/currently-playing` polling
- [ ] Expose real now-playing data via `/status`

### Phase 3 — Album Art Pipeline
- [x] Implement Pillow image processing pipeline (`backend/renderer.py`)
- [ ] Expose `/art/{track_id}` endpoint
- [x] Test output BMP visually on desktop (`tools/preview_renderer.py`, `preview_art.py`)

### Phase 4 — Pico Firmware *(waiting for hardware)*
- [ ] Flash MicroPython on Pico WH
- [ ] Test Wi-Fi connection + `urequests` GET
- [ ] Integrate Waveshare EPD driver
- [ ] Render static test image on e-ink
- [ ] Connect to backend `/status` and render weather screen

### Phase 5 — Full Integration *(waiting for hardware)*
- [ ] Implement full state machine on Pico
- [ ] Implement partial vs. full refresh logic
- [ ] Render album art BMP from backend
- [ ] End-to-end test: play Spotify → display updates

### Phase 6 — Polish & Power *(waiting for hardware)*
- [ ] Add battery + power management module
- [ ] Implement Wi-Fi duty cycling / light sleep
- [ ] Ghosting cleanup (scheduled full refresh)
- [ ] Design/print enclosure

---

## Folder Structure

```
pico-eink-display/
│
├── README.md                    ← this file
├── CLAUDE.md                    ← Claude Code context and conventions
├── .env.example
├── docker-compose.yml
│
├── backend/                     ← FastAPI Docker service + renderer
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                  ← FastAPI app + routes
│   ├── spotify.py               ← Spotify OAuth + polling
│   ├── weather.py               ← Open-Meteo fetching + cache
│   ├── renderer.py              ← Pillow render engine (idle + now-playing)
│   ├── config.py                ← Settings from env vars
│   ├── fonts/                   ← Geist font family (TTF)
│   │   ├── GeistPixel-Circle.ttf
│   │   ├── Geist-Bold.ttf
│   │   ├── Geist-Regular.ttf
│   │   ├── Geist-Light.ttf
│   │   └── GeistMono-Regular.ttf
│   └── photos/                  ← Pre-processed 225×185 greyscale BMPs
│       └── 001.bmp … 057.bmp
│
├── firmware/                    ← MicroPython for Pico WH (planned)
│   ├── main.py                  ← Entry point + state machine
│   ├── config.py                ← Wi-Fi creds, API base URL
│   ├── display.py               ← E-ink refresh helpers
│   ├── api_client.py            ← urequests wrapper
│   └── lib/
│       └── epd_3in7.py          ← Waveshare EPD driver
│
├── tools/                       ← Dev/test utilities (run on Mac)
│   ├── prepare_photos.py        ← Dither raw photos → backend/photos/ BMPs
│   └── preview_renderer.py      ← Render both screens locally, open in Preview
│
└── preview_art.py               ← Fetch live /art/{id} from server, open BMP
```

---

## Open Questions / Future Ideas

- **Enclosure:** 3D printed case? Laser-cut acrylic? Bare PCB aesthetic?
- **Multiple modes:** Could add a third mode — e.g. calendar/next meeting from Google Calendar API
- **Away from home:** Tailscale container on homelab would let the display work on any network
- **OTA updates:** Pico W could pull firmware updates from the backend — useful post-enclosure
- **Second display:** The backend API is generic — could drive a second display (e.g. desk vs. bedroom)
- **Local media:** If using a self-hosted media server (Navidrome etc.) in future, swap out Spotify for a local API

---

*Hardware: Raspberry Pi Pico WH + Waveshare Pico-ePaper-3.7*
*Backend: FastAPI on Docker (Ubuntu homelab)*
*Last updated: February 2026*
