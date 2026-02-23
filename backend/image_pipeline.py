import io
import httpx
import numpy as np
from PIL import Image

_art_cache: dict[str, bytes] = {}
ART_SIZE = 280

# The 4 grey levels the Waveshare 3.7" e-ink understands
LEVELS = np.array([0, 85, 170, 255], dtype=np.float32)


async def get_art_bmp(track_id: str, art_url_spotify: str | None = None) -> bytes:
    if track_id in _art_cache:
        return _art_cache[track_id]

    if art_url_spotify:
        async with httpx.AsyncClient() as client:
            resp = await client.get(art_url_spotify, timeout=10)
            resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    else:
        img = _make_mock_gradient()

    bmp_bytes = _process_image(img)
    _art_cache[track_id] = bmp_bytes
    return bmp_bytes


def _find_nearest_level(value: float) -> float:
    """Snap a float pixel value to the nearest of our 4 grey levels."""
    idx = np.argmin(np.abs(LEVELS - value))
    return LEVELS[idx]


def _process_image(img: Image.Image) -> bytes:
    # 1. Resize
    img = img.resize((ART_SIZE, ART_SIZE), Image.LANCZOS)

    # 2. Convert to greyscale
    img = img.convert("L")

    # 3. Floyd-Steinberg dithering manually via numpy
    # Work in float32 to accumulate error without clipping
    pixels = np.array(img, dtype=np.float32)
    h, w = pixels.shape

    for y in range(h):
        for x in range(w):
            old_val = pixels[y, x]
            new_val = _find_nearest_level(old_val)
            pixels[y, x] = new_val
            err = old_val - new_val

            # Distribute error to neighbours (Floyd-Steinberg kernel):
            #            x     x+1
            #  y:             7/16
            #  y+1:  3/16  5/16  1/16
            if x + 1 < w:
                pixels[y, x + 1]     += err * 7 / 16
            if y + 1 < h:
                if x - 1 >= 0:
                    pixels[y + 1, x - 1] += err * 3 / 16
                pixels[y + 1, x]         += err * 5 / 16
                if x + 1 < w:
                    pixels[y + 1, x + 1] += err * 1 / 16

    # 4. Clip back to 0-255 and convert to uint8
    pixels = np.clip(pixels, 0, 255).astype(np.uint8)

    # 5. Save as BMP
    result_img = Image.fromarray(pixels, mode="L")
    buf = io.BytesIO()
    result_img.save(buf, format="BMP")
    return buf.getvalue()


def _make_mock_gradient() -> Image.Image:
    arr = np.tile(np.linspace(0, 255, ART_SIZE, dtype=np.float32), (ART_SIZE, 1))
    return Image.fromarray(arr.astype(np.uint8), mode="L")
