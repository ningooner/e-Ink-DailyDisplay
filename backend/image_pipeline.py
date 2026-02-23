import asyncio
import io
import httpx
import numpy as np
from PIL import Image

_art_cache: dict[str, bytes] = {}
_art_fetching: dict[str, asyncio.Task] = {}
ART_SIZE = 280


async def get_art_bmp(track_id: str, art_url_spotify: str | None = None) -> bytes:
    if track_id in _art_cache:
        return _art_cache[track_id]
    if track_id in _art_fetching:
        return await _art_fetching[track_id]
    task = asyncio.create_task(_fetch_and_cache(track_id, art_url_spotify))
    _art_fetching[track_id] = task
    return await task


async def _fetch_and_cache(track_id: str, art_url_spotify: str | None) -> bytes:
    if art_url_spotify:
        async with httpx.AsyncClient() as client:
            resp = await client.get(art_url_spotify, timeout=10)
            resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    else:
        img = _make_mock_gradient()

    bmp_bytes = _process_image(img)
    _art_cache[track_id] = bmp_bytes
    _art_fetching.pop(track_id, None)
    return bmp_bytes


def _process_image(img: Image.Image) -> bytes:
    img = img.resize((ART_SIZE, ART_SIZE), Image.LANCZOS).convert("L")

    # Build a palette image with exactly our 4 grey levels
    pal_img = Image.new("P", (1, 1))
    pal_data = [v for v in [0, 85, 170, 255] for _ in range(3)]
    pal_img.putpalette(pal_data + [0] * (768 - len(pal_data)))

    # C-compiled Floyd-Steinberg dithering (~20ms vs ~10s for the Python loop)
    dithered = img.convert("RGB").quantize(palette=pal_img, dither=Image.Dither.FLOYDSTEINBERG)
    result_img = dithered.convert("L")

    buf = io.BytesIO()
    result_img.save(buf, format="BMP")
    return buf.getvalue()


def _make_mock_gradient() -> Image.Image:
    arr = np.tile(np.linspace(0, 255, ART_SIZE, dtype=np.float32), (ART_SIZE, 1))
    return Image.fromarray(arr.astype(np.uint8), mode="L")
