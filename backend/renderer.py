"""
renderer.py — Server-side full-screen renderer for the Pico e-ink display.

Coordinate system: (0,0) = top-left, x right, y down. 480×280 landscape.

Font strategy:
  GeistPixel-Circle  → large clock only
  Geist-Bold         → track name, temperature, forecast highs
  Geist-Regular      → date, artist, day names
  Geist-Light        → album, condition text, small labels
"""

import io, os, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H       = 480, 280
BLACK      = 0
DARK_GREY  = 85
LIGHT_GREY = 170
WHITE      = 255

_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

def _font(name, size):
    path = os.path.join(_FONT_DIR, name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Font not found: {path}")
    return ImageFont.truetype(path, size)

FONT_PIXEL   = "GeistPixel-Circle.ttf"
FONT_BOLD    = "Geist-Bold.ttf"
FONT_REGULAR = "Geist-Regular.ttf"
FONT_LIGHT   = "Geist-Light.ttf"
FONT_MONO    = "GeistMono-Regular.ttf"

# ── NOW-PLAYING LAYOUT ──────────────────────────────────────────────────────
ART_X, ART_Y, ART_W, ART_H = 0, 0, 280, 280
PANEL_X = 285
PANEL_W = W - PANEL_X

TRACK_Y,  TRACK_FONT_SIZE  = 16,  36
ARTIST_Y, ARTIST_FONT_SIZE = 170, 16
ALBUM_Y,  ALBUM_FONT_SIZE  = 200, 13

# ── IDLE LAYOUT ─────────────────────────────────────────────────────────────
TIME_X,      TIME_Y,      TIME_FONT_SIZE  = 20, 10,  80
DATE_X,      DATE_Y,      DATE_FONT_SIZE  = 22, 108, 20
IDLE_DIV_X,  IDLE_DIV_Y,  IDLE_DIV_W     = 20, 145, 210
TEMP_X,      TEMP_Y,      TEMP_FONT_SIZE  = 20, 155, 34
COND_X,      COND_Y,      COND_FONT_SIZE  = 110, 165, 16


# ── PHOTO SLOT (idle screen, right side) ────────────────────────────────────
PHOTO_X       = 248    # left edge of photo slot
PHOTO_Y       = 10     # top edge
PHOTO_W       = 225    # width  — must match prepare_photos.py
PHOTO_H       = 185    # height — must match prepare_photos.py
PHOTO_ROTATE  = 10     # minutes per photo

FORECAST_Y         = 208
FORECAST_DIV_Y     = FORECAST_Y - 8
FORECAST_COLS      = [10, 88, 166, 244, 322, 400]   # 6 hourly slots
FORECAST_COL_W     = 72
FC_HOUR_SIZE       = 13
FC_TEMP_SIZE       = 14

# ── WEATHER ICONS ────────────────────────────────────────────────────────────
def _sun(d, cx, cy, s=16):
    r = s//2
    d.ellipse([cx-r,cy-r,cx+r,cy+r], outline=BLACK, width=2)
    for i in range(8):
        a = math.radians(i*45)
        d.line([int(cx+(r+3)*math.cos(a)), int(cy+(r+3)*math.sin(a)),
                int(cx+(r+3+s//3)*math.cos(a)), int(cy+(r+3+s//3)*math.sin(a))],
               fill=BLACK, width=2)

def _cloud(d, cx, cy, s=16):
    d.ellipse([cx-s, cy-s//2, cx+s, cy+s//2],   fill=DARK_GREY)
    d.ellipse([cx-s, cy-s,    cx,   cy],          fill=DARK_GREY)
    d.ellipse([cx,   cy-s*3//4, cx+s*3//4, cy],   fill=DARK_GREY)

def _rain(d, cx, cy, s=16):
    _cloud(d, cx, cy-s//3, s)
    for dx in [-s//2, 0, s//2]:
        d.line([cx+dx, cy+s//3, cx+dx-3, cy+s], fill=BLACK, width=2)

def _snow(d, cx, cy, s=16):
    _cloud(d, cx, cy-s//3, s)
    for i in range(3):
        x, y = cx+(i-1)*s//2, cy+s//2
        for a in [0, 60, 120]:
            r = math.radians(a)
            d.line([x, y, int(x+(s//3)*math.cos(r)), int(y+(s//3)*math.sin(r))],
                   fill=BLACK, width=2)

def _overcast(d, cx, cy, s=16):
    _cloud(d, cx-s//4, cy, s*3//4)
    _cloud(d, cx+s//4, cy-s//4, s*3//4)

def _partly(d, cx, cy, s=16):
    _sun(d, cx-s//3, cy+s//3, s*2//3)
    _cloud(d, cx+s//4, cy-s//4, s*2//3)

def _storm(d, cx, cy, s=16):
    _cloud(d, cx, cy-s//3, s)
    mx, my = cx, cy+s//4
    d.polygon([(mx,my),(mx-6,my+10),(mx-2,my+10),(mx-6,my+20),(mx+4,my+8),(mx,my+8)], fill=BLACK)

def _fog(d, cx, cy, s=16):
    for i, dy in enumerate([-s//3, 0, s//3]):
        d.line([cx-s+(i%2)*6, cy+dy, cx+s, cy+dy], fill=DARK_GREY, width=3)

ICONS = {"sunny":_sun,"partly_cloudy":_partly,"cloudy":_overcast,
         "overcast":_overcast,"fog":_fog,"drizzle":_rain,"rain":_rain,
         "snow":_snow,"showers":_rain,"thunderstorm":_storm}

def _icon(d, cond, cx, cy, s=20):
    fn = ICONS.get((cond or "").lower())
    if fn: fn(d, cx, cy, s)
    else:  d.text((cx-5, cy-8), "?", fill=BLACK)

# ── TEXT HELPERS ─────────────────────────────────────────────────────────────
def _trunc(d, text, font, max_w):
    if d.textlength(text, font=font) <= max_w: return text
    while text and d.textlength(text+"…", font=font) > max_w: text = text[:-1]
    return text+"…"

def _wrap(d, text, font, x, y, max_w, max_lines=2, fill=BLACK, spacing=4):
    words, lines, cur = text.split(), [], ""
    for word in words:
        test = (cur+" "+word).strip()
        if d.textlength(test, font=font) <= max_w: cur = test
        else:
            if cur: lines.append(cur)
            cur = word
        if len(lines) == max_lines: break
    if cur and len(lines) < max_lines: lines.append(cur)
    if lines:
        last = lines[-1]
        while last and d.textlength(last+"…", font=font) > max_w: last = last[:-1]
        if d.textlength(lines[-1], font=font) > max_w: lines[-1] = last+"…"
    lh = font.size + spacing
    for i, line in enumerate(lines): d.text((x, y+i*lh), line, font=font, fill=fill)
    return y + len(lines)*lh

# ── NOW-PLAYING ──────────────────────────────────────────────────────────────
def render_now_playing(status, art_bytes):
    img = Image.new("L", (W,H), WHITE)
    d   = ImageDraw.Draw(img)
    sp  = status.get("spotify", {})

    art = Image.open(io.BytesIO(art_bytes)).convert("L").resize((ART_W,ART_H), Image.LANCZOS)
    img.paste(art, (ART_X, ART_Y))
    d.line([PANEL_X-3, 0, PANEL_X-3, H], fill=LIGHT_GREY, width=1)

    ft = _font(FONT_PIXEL,   TRACK_FONT_SIZE)
    fa = _font(FONT_MONO,    ARTIST_FONT_SIZE)
    fl = _font(FONT_LIGHT,   ALBUM_FONT_SIZE)
    fs = _font(FONT_LIGHT,   13)

    _wrap(d, sp.get("track","Unknown Track"), ft,
          PANEL_X, TRACK_Y, PANEL_W-5, max_lines=3, fill=BLACK)
    d.text((PANEL_X, ARTIST_Y),
           _trunc(d, sp.get("artist",""), fa, PANEL_W-5), font=fa, fill=DARK_GREY)
    d.text((PANEL_X, ALBUM_Y),
           _trunc(d, sp.get("album",""),  fl, PANEL_W-5), font=fl, fill=LIGHT_GREY)
    # clock bottom-right
    time_str = status.get("time","")
    tw = int(d.textlength(time_str, font=fs))
    d.text((W - tw - 6, H - fs.size - 6), time_str, font=fs, fill=LIGHT_GREY)
    return img


# ── PHOTO SLOT HELPER ────────────────────────────────────────────────────────
def _draw_photo_slot(img, draw):
    """Pick a photo by 10-minute block and paste it into the idle screen."""
    import glob
    from datetime import datetime

    photos_dir = os.path.join(os.path.dirname(__file__), "photos")
    bmps = sorted(glob.glob(os.path.join(photos_dir, "*.bmp")))

    if not bmps:
        # No photos yet — draw a placeholder grey rectangle
        draw.rectangle([PHOTO_X, PHOTO_Y,
                        PHOTO_X + PHOTO_W - 1, PHOTO_Y + PHOTO_H - 1],
                       fill=LIGHT_GREY)
        return

    # Pick photo by 10-minute block within the day — fully deterministic
    now        = datetime.now()
    # Seed with the 10-minute block so the same photo shows for the full 10 min,
    # then a new random one is picked. Reproducible but not sequential.
    block = (now.hour * 60 + now.minute) // PHOTO_ROTATE
    import random
    rng = random.Random(block)
    idx = rng.randint(0, len(bmps) - 1)
    photo_path = bmps[idx]

    photo = Image.open(photo_path).convert("L")
    # Safety resize in case dimensions differ from expected
    if photo.size != (PHOTO_W, PHOTO_H):
        photo = photo.resize((PHOTO_W, PHOTO_H), Image.LANCZOS)

    img.paste(photo, (PHOTO_X, PHOTO_Y))


# ── IDLE ─────────────────────────────────────────────────────────────────────
def render_idle(status):
    img = Image.new("L", (W,H), WHITE)
    d   = ImageDraw.Draw(img)
    wx  = status.get("weather", {})
    fc  = wx.get("forecast", [])

    fT  = _font(FONT_PIXEL,   TIME_FONT_SIZE)
    fDt = _font(FONT_REGULAR, DATE_FONT_SIZE)
    fTp = _font(FONT_BOLD,    TEMP_FONT_SIZE)
    fCo = _font(FONT_LIGHT,   COND_FONT_SIZE)
    fFd = _font(FONT_LIGHT,   FC_HOUR_SIZE)
    fFt = _font(FONT_BOLD,    FC_TEMP_SIZE)

    d.text((TIME_X, TIME_Y), status.get("time","--:--"), font=fT, fill=BLACK)
    d.text((DATE_X, DATE_Y), status.get("date",""),      font=fDt, fill=DARK_GREY)
    d.line([IDLE_DIV_X, IDLE_DIV_Y, IDLE_DIV_X+IDLE_DIV_W, IDLE_DIV_Y],
           fill=LIGHT_GREY, width=1)

    d.text((TEMP_X, TEMP_Y), f"{wx.get('temp_c','--')}°", font=fTp, fill=BLACK)

    cond  = wx.get("condition","")
    label = cond.replace("_"," ").title()
    d.text((COND_X, COND_Y), label, font=fCo, fill=DARK_GREY)
    _icon(d, cond,
          COND_X + int(d.textlength(label, font=fCo)) + 24,
          COND_Y + COND_FONT_SIZE//2, s=14)


    # ── Photo slot ────────────────────────────────────────────────────────
    _draw_photo_slot(img, d)

    d.line([0, FORECAST_DIV_Y, W, FORECAST_DIV_Y], fill=LIGHT_GREY, width=1)

    for i, slot in enumerate(fc[:6]):
        cx = FORECAST_COLS[i]
        # Hour label
        d.text((cx, FORECAST_Y), slot.get("hour",""), font=fFd, fill=DARK_GREY)
        # Icon — right-aligned in column so it never overlaps the hour text
        _icon(d, slot.get("condition",""),
              cx + FORECAST_COL_W - 14, FORECAST_Y + FC_HOUR_SIZE + 16, s=13)
        # Temp
        d.text((cx, FORECAST_Y + FC_HOUR_SIZE + 34),
               f"{slot.get('temp_c','--')}°",
               font=fFt, fill=BLACK)
        # Vertical separator (not after last)
        if i < 5:
            sx = FORECAST_COLS[i+1] - 4
            d.line([sx, FORECAST_DIV_Y+4, sx, H-4], fill=LIGHT_GREY, width=1)

    return img

# ── DITHERING ────────────────────────────────────────────────────────────────
def _dither(img):
    LEVELS = np.array([0,85,170,255], dtype=np.float32)
    arr    = np.array(img.convert("L"), dtype=np.float32)
    h, w   = arr.shape
    for y in range(h):
        for x in range(w):
            old = arr[y,x]
            new = LEVELS[np.argmin(np.abs(LEVELS-old))]
            arr[y,x] = new
            err = old - new
            if x+1 < w:           arr[y,   x+1] += err*7/16
            if y+1 < h:
                if x-1 >= 0:      arr[y+1, x-1] += err*3/16
                arr[y+1, x  ]    += err*5/16
                if x+1 < w:       arr[y+1, x+1] += err*1/16
    return Image.fromarray(np.clip(arr,0,255).astype(np.uint8), mode="L")

def render_to_bmp(img):
    buf = io.BytesIO()
    _dither(img).save(buf, format="BMP")
    return buf.getvalue()

def build_now_playing_frame(status, art_bytes):
    return render_to_bmp(render_now_playing(status, art_bytes))

def build_idle_frame(status):
    return render_to_bmp(render_idle(status))
