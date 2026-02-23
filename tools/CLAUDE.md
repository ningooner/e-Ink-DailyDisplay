# CLAUDE.md — tools/

Dev utilities that run on the Mac (not on the server or Pico). Use `~/miniforge3/bin/python3` as the interpreter.

---

## prepare_photos.py

Converts raw photos into e-ink-ready BMPs for the idle screen photo rotation slot.

**Input dir:** `~/Desktop/rendered eink pics/` (any JPEGs, PNGs, WebP, TIFF, BMP)
**Output dir:** `backend/photos/` (sequentially named 001.bmp, 002.bmp, ...)

**Run:**
```bash
~/miniforge3/bin/python3 ~/Desktop/pico-eink-display/tools/prepare_photos.py
```

**What it does:**
1. Clears all existing BMPs from `backend/photos/`
2. Finds all image files in the raw dir, sorted by filename
3. For each image:
   - Crops to fill 225×185 (no letterboxing, centre-crop)
   - Converts to greyscale
   - Applies Floyd-Steinberg dithering to 4 levels (0, 85, 170, 255)
   - Saves as `001.bmp`, `002.bmp`, etc.
4. Prints an `scp` command to copy results to the server

**After running, copy to server:**
```bash
scp ~/Desktop/pico-eink-display/backend/photos/*.bmp cribbbserver:~/pico-eink-display/backend/photos/
```

**Critical constraint:** Output dimensions (225×185) must match `PHOTO_W` / `PHOTO_H` in `backend/renderer.py`. If you change the photo slot size in the renderer, update `PHOTO_W` / `PHOTO_H` here too, then re-run this script.

---

## preview_renderer.py

Renders both idle and now-playing screens using mock data and opens them in macOS Preview. Use this for layout iteration without needing the server or Pico.

**Run:**
```bash
~/miniforge3/bin/python3 ~/Desktop/pico-eink-display/tools/preview_renderer.py
```

**Outputs:**
- `/tmp/preview_idle.png` — idle screen (2× upscaled for readability)
- `/tmp/preview_now_playing.png` — now-playing screen (2× upscaled)

Both files are auto-opened in Preview.

**Mock data:** Hardcoded `MOCK_STATUS` dict at the top of the file — edit it to test different weather conditions, track names, etc.

**Album art in preview:** Uses a synthetic grey gradient (no real API call). To test with real art, use `preview_art.py` instead.

**Import path:** Adds the repo root to `sys.path` so it can import `from backend.renderer import ...`. Run from the repo root or use the absolute path shown above.

---

## preview_art.py (repo root)

Fetches a live album art BMP from the running server and opens it in macOS Preview. Useful for checking the dithering pipeline end-to-end with real Spotify data.

**Run:**
```bash
~/miniforge3/bin/python3 ~/Desktop/pico-eink-display/preview_art.py
```

**Requires:** Server running at `http://100.84.37.35:8765` with Spotify actively playing.

**What it does:**
1. Calls `GET /status` to get the current `track_id`
2. Calls `GET /art/{track_id}` to download the processed BMP
3. Saves to a temp file and opens in Preview

**If nothing is playing:** Prints an error and exits — start Spotify first.

**Server address:** Hardcoded as `API_BASE = "http://100.84.37.35:8765"` in the file. Update if the server IP changes.
