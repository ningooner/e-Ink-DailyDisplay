# PaperDeck — Backend

> FastAPI service that runs in Docker on the home server. Handles Spotify OAuth, weather fetching, full-screen rendering, and serving pre-processed frames to the Pico over Wi-Fi.

---

## Server Context

| Property | Value |
|---|---|
| Hostname | `cribbbserver` |
| OS | Ubuntu 24.04.3 LTS |
| Docker | 27.5.1 |
| Tailscale IP | `100.84.37.35` |
| LAN IP | `192.168.1.220` |
| Project path | `~/pico-eink-display/` |
| API port (host) | `8765` |

---

## Files

```
backend/
├── Dockerfile          ← python:3.11-slim + libjpeg
├── docker-compose.yml  ← service definition (run from backend/ with -f flag)
├── requirements.txt    ← fastapi, uvicorn, httpx, Pillow, numpy
├── config.py           ← reads all settings from env vars
├── main.py             ← FastAPI app: /health, /status, /art/{id}, /frame
├── weather.py          ← Open-Meteo fetcher with 15-min cache
├── spotify.py          ← Spotify OAuth + now-playing polling
├── image_pipeline.py   ← Floyd-Steinberg dithering → 280×280 BMP
├── renderer.py         ← Pillow render engine for both screens + 4gray encoder
├── fonts/              ← Geist font family (TTF, do not modify)
└── photos/             ← Pre-processed 225×185 greyscale BMPs (gitignored)
```

---

## API Endpoints

### `GET /health`

Liveness check.

```json
{"status": "ok"}
```

---

### `GET /status`

Aggregates current time, weather, and Spotify state into a single JSON response. The Pico polls this to detect what has changed before deciding whether to fetch a new frame.

```json
{
  "time": "15:21",
  "date": "Thu 19 Feb",
  "weather": {
    "temp_c": 8,
    "condition": "drizzle",
    "forecast": [
      {"hour": "16:00", "temp_c": 7,  "condition": "rain"},
      {"hour": "20:00", "temp_c": 5,  "condition": "overcast"},
      {"hour": "00:00", "temp_c": 3,  "condition": "cloudy"},
      {"hour": "04:00", "temp_c": 2,  "condition": "cloudy"},
      {"hour": "08:00", "temp_c": 4,  "condition": "partly_cloudy"},
      {"hour": "12:00", "temp_c": 9,  "condition": "sunny"}
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

Valid `condition` strings: `sunny`, `partly_cloudy`, `cloudy`, `overcast`, `fog`, `drizzle`, `rain`, `snow`, `showers`, `thunderstorm`.

---

### `GET /frame`

**The primary endpoint the Pico uses to update its display.**

Returns a packed 2bpp binary frame (exactly **33,600 bytes**) ready to write directly into the Waveshare Pico-ePaper-3.7 framebuffer.

- Renders the **now-playing screen** if Spotify is active, otherwise the **idle screen**
- Calling `/frame` implicitly refreshes Spotify and weather state (same as `/status`)
- `Content-Type: application/octet-stream`, `Cache-Control: no-store`

**Wire format:** 4 pixels packed per byte, MSB first, rows top-to-bottom, left-to-right.
Grey level encoding: `0x00` = black, `0x01` = dark grey, `0x02` = light grey, `0x03` = white.

Verify with:
```bash
curl -s http://localhost:8765/frame | wc -c   # should print 33600
```

---

### `GET /art/{track_id}`

Returns a **280×280** 4-level greyscale BMP (`Content-Type: image/bmp`), cached in memory per `track_id`. Returns 404 if `/status` hasn't been called yet for this track (the CDN URL is populated on each `/status` call).

---

## Weather — MeteoSwiss ICON-CH2

Open-Meteo provides a MeteoSwiss endpoint using the ICON-CH2 model (2km grid, updated every 6 hours) — the most accurate available source for the Winterthur/Zurich area without a direct API key.

Forecast: 6 hourly slots, 4 hours apart, starting from the next full hour after now. Weather data is cached in-memory for 15 minutes (`WEATHER_CACHE_TTL=900`).

WMO code → condition string mapping is defined in `weather.py`.

---

## Spotify Integration

### OAuth Setup (one-time)

Uses Authorization Code Flow. Scopes: `user-read-currently-playing`, `user-read-playback-state`.

Run `tools/spotify_auth.py` on the Mac for the one-time flow:
1. Opens Spotify auth URL in the browser
2. Spins up a temporary callback server on `http://127.0.0.1:9999`
3. Exchanges the code for a refresh token
4. Prints the refresh token to add to `.env`

> **Note:** Spotify requires `http://127.0.0.1` (not `localhost`) as the redirect URI for loopback since April 2025.

### Token Refresh

`spotify.py` refreshes the access token automatically whenever it is within 30 seconds of expiry.

### Art URL Store

Each `get_now_playing()` call stores `track_id → Spotify CDN URL` in `_art_url_store` (in-memory). Both `/art/{track_id}` and `/frame` look up this store to fetch album art.

---

## Rendering Pipeline

### Album Art (`image_pipeline.py`)

1. Download JPEG from Spotify CDN (typically 640×640)
2. Resize to 280×280 via `Image.LANCZOS`
3. Convert to greyscale (`convert("L")`)
4. Floyd-Steinberg dithering — snaps each pixel to the nearest of 4 levels (0, 85, 170, 255) and distributes error using the standard FS kernel
5. Save as BMP, cache by `track_id`

### Full Screen Renderer (`renderer.py`)

Renders a complete 480×280 PIL image for either screen:

- **Idle:** clock (GeistPixel-Circle, 80pt), date, current weather + icon, 6-slot hourly forecast, rotating photo from `backend/photos/`
- **Now-playing:** 280×280 album art on the left, track/artist/album on the right (Geist fonts)

`img_to_4gray_buffer(img)` converts the rendered PIL image to the 33,600-byte 2bpp wire format served by `/frame`.

**Why 4 grey levels?** The Waveshare Pico-ePaper-3.7 supports exactly 4 greyscale levels: 0 (black), 85, 170, 255 (white).

---

## Setting Up From Scratch

### Prerequisites

- Docker + Docker Compose installed on the server
- Git installed (`sudo apt install git -y` on Ubuntu)
- A Spotify app registered at [developer.spotify.com](https://developer.spotify.com) with `http://127.0.0.1:9999/callback` as a redirect URI

### Step 1 — Get a Spotify refresh token (Mac)

```bash
~/miniforge3/bin/python3 tools/spotify_auth.py
# Follow the browser prompt, then copy the printed refresh token
```

### Step 2 — Clone the repo on the server

```bash
cd ~
git clone https://github.com/ningooner/e-Ink-DailyDisplay.git pico-eink-display
cd pico-eink-display
```

### Step 3 — Create the `.env` file

The compose file reads `backend/.env`. Create it now:

```bash
cat > backend/.env << 'EOF'
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REFRESH_TOKEN=your_refresh_token
HOME_LAT=47.48728357105892
HOME_LON=8.712626997793446
WEATHER_CACHE_TTL=900
EOF
```

> Update `HOME_LAT` / `HOME_LON` for your location.

### Step 4 — Build and start

```bash
cd ~/pico-eink-display
docker compose -f backend/docker-compose.yml build
docker compose -f backend/docker-compose.yml up -d
```

### Step 5 — Verify

```bash
curl -s http://localhost:8765/health
# {"status":"ok"}

curl -s http://localhost:8765/status | python3 -m json.tool

curl -s http://localhost:8765/frame | wc -c
# 33600
```

---

## Common Commands

```bash
# Pull updates and rebuild
cd ~/pico-eink-display
git pull
docker compose -f backend/docker-compose.yml build
docker compose -f backend/docker-compose.yml up -d

# Restart without rebuild (e.g. after editing .env)
docker compose -f backend/docker-compose.yml restart

# View live logs
docker logs -f pico-api

# Test endpoints
curl http://localhost:8765/health
curl http://localhost:8765/status | python3 -m json.tool
curl -s http://localhost:8765/frame | wc -c

# Fetch and preview art on Mac
~/miniforge3/bin/python3 tools/preview_art.py

# Re-run Spotify OAuth (if refresh token ever expires)
~/miniforge3/bin/python3 tools/spotify_auth.py
```

---

## Environment Variables

Stored in `backend/.env` on the server (gitignored). See `.env.example` for the template.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SPOTIFY_CLIENT_ID` | Yes | — | Spotify app client ID |
| `SPOTIFY_CLIENT_SECRET` | Yes | — | Spotify app client secret |
| `SPOTIFY_REFRESH_TOKEN` | Yes | — | Long-lived OAuth refresh token |
| `HOME_LAT` | No | `47.487` | Latitude for weather |
| `HOME_LON` | No | `8.712` | Longitude for weather |
| `WEATHER_CACHE_TTL` | No | `900` | Weather cache lifetime (seconds) |

> If the client secret is ever exposed, regenerate it immediately in the Spotify Developer Dashboard and update `.env`.

---

## Known Limitations

- **Art URL store is in-memory only.** If the container restarts while a track is playing, the first `/frame` call will return an idle screen until `/status` is polled and the URL is re-populated. The Pico's polling loop handles this naturally.
- **Floyd-Steinberg dithering is a pure Python loop** (~2s for 280×280). Acceptable since it only runs once per track and the result is cached.
- **Timezone is hardcoded to CET (UTC+1).** CEST (UTC+2, summer) is not handled — will need `zoneinfo` when clocks change in March.
- **Weather cache does not survive container restarts.** The first request after a restart hits Open-Meteo directly, which is fine.
- **Photos directory is gitignored.** After cloning, `backend/photos/` is empty — the idle screen will show a grey placeholder until BMPs are copied over via `scp`.
