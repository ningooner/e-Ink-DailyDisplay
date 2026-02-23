# CLAUDE.md — backend/

This directory contains the server-side code that runs in Docker on the home server.

---

## Current State

Only `renderer.py` is fully implemented. The FastAPI app (`main.py`, `spotify.py`, `weather.py`, `config.py`) and `Dockerfile` are not yet created.

---

## renderer.py — The Core Render Engine

`renderer.py` is the most complete file in the project. It takes a `/status` JSON dict (and optionally album art bytes) and returns a 480×280 greyscale BMP ready for the Pico's framebuffer.

### Public API

```python
from backend.renderer import build_idle_frame, build_now_playing_frame

# Both return raw BMP bytes (already dithered)
bmp: bytes = build_idle_frame(status_dict)
bmp: bytes = build_now_playing_frame(status_dict, art_bytes)

# Lower-level — returns a PIL Image (mode "L") before dithering
img = render_idle(status_dict)
img = render_now_playing(status_dict, art_bytes)

# Apply dithering + BMP serialisation to any PIL Image
bmp = render_to_bmp(img)
```

### Layout Constants

**Canvas:** 480 × 280 px (W × H), coordinate origin top-left.

**Now-Playing layout:**
- Album art: `(ART_X=0, ART_Y=0)` — 280×280 px, left side
- Vertical divider at x=282
- Info panel starts at `PANEL_X=285`, width=195 px
- Track name: y=16, GeistPixel-Circle 36pt, up to 3 lines
- Artist: y=170, GeistMono 16pt, single line truncated
- Album: y=200, Geist-Light 13pt, single line truncated
- Clock (bottom-right corner): Geist-Light 13pt

**Idle layout:**
- Clock: `(TIME_X=20, TIME_Y=10)`, GeistPixel-Circle 80pt
- Date: `(DATE_X=22, DATE_Y=108)`, Geist-Regular 20pt
- Divider at y=145
- Temperature: `(TEMP_X=20, TEMP_Y=155)`, Geist-Bold 34pt
- Condition label + icon: `(COND_X=110, COND_Y=165)`, Geist-Light 16pt
- Photo slot: top-right, `(PHOTO_X=248, PHOTO_Y=10)`, 225×185 px
- Forecast bar: y=208, 6 hourly columns at x=[10, 88, 166, 244, 322, 400]

### Font Strategy

| Font file | Constant | Used for |
|---|---|---|
| `GeistPixel-Circle.ttf` | `FONT_PIXEL` | Clock (large pixel aesthetic) |
| `Geist-Bold.ttf` | `FONT_BOLD` | Track name, temperature, forecast temps |
| `Geist-Regular.ttf` | `FONT_REGULAR` | Date, artist |
| `Geist-Light.ttf` | `FONT_LIGHT` | Album, condition label, small labels |
| `GeistMono-Regular.ttf` | `FONT_MONO` | Artist name (monospace) |

Fonts are loaded via `_font(name, size)` which resolves paths relative to `backend/fonts/`.

### Greyscale Palette

| Name | Value | Typical use |
|---|---|---|
| BLACK | 0 | Primary text, outlines |
| DARK_GREY | 85 | Secondary text (artist, date) |
| LIGHT_GREY | 170 | Tertiary text (album, dividers) |
| WHITE | 255 | Background |

### Dithering

`_dither(img)` applies Floyd-Steinberg error diffusion to quantise any greyscale image to the 4 e-ink levels (0, 85, 170, 255). It's implemented in NumPy for reasonable speed. Applied automatically by `render_to_bmp()`.

Error diffusion weights:
- Right pixel: 7/16
- Bottom-left: 3/16
- Bottom: 5/16
- Bottom-right: 1/16

### Weather Icons

Drawn programmatically with PIL primitives (no image files). Each icon is a function `fn(draw, cx, cy, s)` where `cx/cy` is the centre and `s` is the size scale.

Valid condition strings and their icon functions:

| Condition string | Icon |
|---|---|
| `sunny` | Circle + 8 rays |
| `partly_cloudy` | Small sun behind cloud |
| `cloudy` | Double cloud shape |
| `overcast` | Double cloud shape (same as cloudy) |
| `fog` | 3 horizontal dashed lines |
| `drizzle` | Cloud + rain lines |
| `rain` | Cloud + rain lines (same as drizzle) |
| `showers` | Cloud + rain lines |
| `snow` | Cloud + asterisk shapes |
| `thunderstorm` | Cloud + lightning bolt |

To add a new condition: define a `_newcond(d, cx, cy, s)` function and add it to the `ICONS` dict.

### Photo Rotation

`_draw_photo_slot()` picks a BMP from `backend/photos/` deterministically by 10-minute time block. The selection uses `random.Random(block)` seeded by the block index — same photo for the full 10 minutes, then a new random one. If no photos exist, a grey placeholder rectangle is drawn.

**Critical constraint:** Photos must be exactly 225×185 px (PHOTO_W × PHOTO_H). The `tools/prepare_photos.py` script produces them at this size. The renderer does a safety resize if dimensions differ, but the pipeline should always produce the right size.

---

## Files To Build (FastAPI Backend)

When building `main.py`, follow this pattern:

```python
# main.py skeleton
from fastapi import FastAPI
from fastapi.responses import Response
from backend.renderer import build_idle_frame, build_now_playing_frame

app = FastAPI()

@app.get("/status")
async def status():
    # Aggregate time, weather, spotify → return unified dict

@app.get("/art/{track_id}")
async def art(track_id: str):
    # Fetch album art JPEG → pass through renderer → return BMP
    bmp = build_now_playing_frame(status, art_bytes)
    return Response(content=bmp, media_type="image/bmp")
```

The renderer is already built and tested — `main.py` just needs to wire it to real data sources.

---

## Dependencies

```
pillow
numpy
fastapi
uvicorn
httpx
python-dotenv
```

(Add `spotipy` or handle OAuth manually for Spotify.)
