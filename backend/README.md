# PaperDeck — Backend

> FastAPI service that runs in Docker on the home server. Provides the Pico's single source of truth via `/status` and pre-processed album art via `/art/{track_id}`.
>
> Setup completed: February 19, 2026

---

## Server Context

| Property | Value |
|---|---|
| Hostname | `cribbbserver` |
| OS | Ubuntu 24.04.3 LTS |
| Docker | 27.5.1 |
| Tailscale IP | 100.84.37.35 |
| LAN IP | 192.168.1.220 |
| Project path | `~/pico-eink-display/` |
| API port (host) | 8765 |

---

## Files

```
backend/
├── Dockerfile          ← python:3.11-slim + libjpeg
├── requirements.txt    ← fastapi, uvicorn, httpx, Pillow, numpy
├── config.py           ← reads all settings from env vars
├── main.py             ← FastAPI app: /health, /status, /art/{track_id}
├── weather.py          ← Open-Meteo fetcher with 15-min cache
├── spotify.py          ← Spotify OAuth + now-playing polling
├── image_pipeline.py   ← Floyd-Steinberg dithering → BMP output
├── renderer.py         ← Pillow render engine for both display screens
├── fonts/              ← Geist font family (TTF, do not modify)
└── photos/             ← Pre-processed 225×185 greyscale BMPs (57 files)
```

---

## API Endpoints

### `GET /health`

Liveness check.

```json
{"status": "ok"}
```

### `GET /status`

The Pico's single source of truth. Aggregates time, weather, and Spotify state.

```json
{
  "time": "15:21",
  "date": "Thu 19 Feb",
  "weather": {
    "temp_c": 8,
    "condition": "drizzle",
    "forecast": [
      {"day": "Fri", "high": 8,  "low": 3, "condition": "snow"},
      {"day": "Sat", "high": 11, "low": 5, "condition": "drizzle"},
      {"day": "Sun", "high": 13, "low": 6, "condition": "overcast"}
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

> `/status` must be called at least once for a given track before `/art/{track_id}` will work — the Spotify CDN URL is stored in memory on each `/status` call.

### `GET /art/{track_id}`

Returns a 280×280 4-level greyscale BMP (`Content-Type: image/bmp`), cached in memory per `track_id`. Returns 404 if `/status` hasn't been called yet for this track.

---

## Weather — MeteoSwiss ICON-CH2

Open-Meteo provides a dedicated MeteoSwiss endpoint using the ICON-CH2 model (2km grid, updated every 6 hours). This is the most accurate available source for the Winterthur/Zurich area without a direct MeteoSwiss API key.

**Open-Meteo URL:**
```
https://api.open-meteo.com/v1/forecast
  ?latitude=47.48728357105892
  &longitude=8.712626997793446
  &current=temperature_2m,weather_code
  &daily=temperature_2m_max,temperature_2m_min,weather_code
  &forecast_days=4
  &timezone=Europe/Zurich
  &models=meteoswiss_icon_ch2
```

WMO code → condition string mapping is defined in `weather.py`. Weather data is cached in-memory for 15 minutes (`WEATHER_CACHE_TTL=900`).

---

## Spotify Integration

### OAuth Setup (one-time, completed)

Uses Authorization Code Flow. Scopes granted: `user-read-currently-playing`, `user-read-playback-state`.

The `tools/spotify_auth.py` script handles the one-time flow:
1. Spins up a temporary HTTP server on `http://127.0.0.1:9999`
2. Opens the Spotify auth URL in the browser
3. Catches the authorization code from the callback
4. Exchanges it for access token + refresh token
5. Prints the refresh token for `.env`

> **Note:** As of April 2025, Spotify enforces `http://127.0.0.1` (not `localhost`) as the redirect URI for loopback.

### Token Refresh

`spotify.py` refreshes the access token automatically. If the token is within 30 seconds of expiry on each `get_now_playing()` call, it is refreshed before the API call is made.

### Art URL Store

When `get_now_playing()` fetches a track, it stores `track_id → Spotify CDN URL` in `_art_url_store` (in-memory dict). The `/art/{track_id}` endpoint looks up this store to fetch the JPEG.

---

## Album Art Pipeline

Defined in `image_pipeline.py`:

1. **Download** — JPEG fetched from Spotify CDN (typically 640×640)
2. **Resize** — `Image.LANCZOS` to 280×280
3. **Greyscale** — PIL `convert("L")`
4. **Floyd-Steinberg dithering** — NumPy implementation; snaps each pixel to nearest of 4 levels (0, 85, 170, 255) and distributes error using standard FS kernel (7/16, 3/16, 5/16, 1/16)
5. **BMP output** — saved via PIL, returned as bytes

Result is cached in `_art_cache` dict by `track_id`. Cache lives for the lifetime of the container — restarts clear it, which is fine since the Pico always calls `/status` before `/art/`.

**Why 4 levels?** The Waveshare Pico-ePaper-3.7 supports exactly 4 greyscale levels: 0 (black), 85, 170, 255 (white).

---

## Docker

### `docker-compose.yml`

```yaml
services:
  pico-api:
    build: ./backend
    container_name: pico-api
    ports:
      - "8765:8000"
    env_file: .env
    restart: unless-stopped
```

### `Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-turbo-progs \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `requirements.txt`

```
fastapi==0.115.8
uvicorn[standard]==0.34.0
httpx==0.28.1
Pillow==11.1.0
numpy==2.2.3
python-dotenv==1.0.1
```

---

## Environment Variables

Stored in `~/pico-eink-display/.env` on the server (never committed). See `.env.example` for the template.

```env
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REFRESH_TOKEN=...
HOME_LAT=47.48728357105892
HOME_LON=8.712626997793446
WEATHER_CACHE_TTL=900
```

> If the client secret is ever accidentally exposed, regenerate it immediately in the Spotify Developer Dashboard and update `.env`.

---

## Common Commands

```bash
# Start / rebuild after code changes
cd ~/pico-eink-display && docker compose up --build -d

# Restart without rebuild (e.g. after editing .env)
docker compose restart

# View live logs
docker logs -f pico-api

# Test endpoints
curl http://localhost:8765/health
curl http://localhost:8765/status | python3 -m json.tool
curl -o /tmp/art.bmp http://localhost:8765/art/<track_id>

# Preview dithered art on Mac
~/miniforge3/bin/python3 ~/Desktop/pico-eink-display/preview_art.py

# Re-run Spotify OAuth (if refresh token expires)
~/miniforge3/bin/python3 ~/Desktop/pico-eink-display/tools/spotify_auth.py
```

---

## Known Limitations

- **Art URL store is in-memory only.** If the container restarts while a track is playing, the first `/art/` call will 404 until `/status` is called again. The Pico's polling loop handles this naturally since it always calls `/status` first.
- **Floyd-Steinberg is pure Python** (~2s for 280×280). Acceptable since it only runs once per track. Could be vectorised with NumPy if needed.
- **Timezone is hardcoded to CET (UTC+1).** DST (CEST, UTC+2) is not handled — will need `pytz`/`zoneinfo` when clocks change.
- **Weather cache does not survive restarts.** First request after a restart hits Open-Meteo directly.
