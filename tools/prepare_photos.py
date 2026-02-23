"""
prepare_photos.py — Dithers raw photos into e-ink ready BMPs.

Usage:
    ~/miniforge3/bin/python3 ~/Desktop/pico-eink-display/tools/prepare_photos.py

Input:  ~/Desktop/pico-photos-raw/   (any JPEGs or PNGs, any size)
Output: ~/Desktop/pico-eink-display/backend/photos/  (001.bmp, 002.bmp, ...)

Run this every time you add or change photos, then scp the BMPs to the server.
"""

import os, sys
import numpy as np
from PIL import Image

RAW_DIR  = os.path.expanduser("~/Desktop/rendered eink pics")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "..", "backend", "photos")
OUT_DIR  = os.path.realpath(OUT_DIR)

# Must match PHOTO_W / PHOTO_H in renderer.py
PHOTO_W  = 225
PHOTO_H  = 185

LEVELS   = np.array([0, 85, 170, 255], dtype=np.float32)
EXTS     = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"}


def dither(img: Image.Image) -> Image.Image:
    """Floyd-Steinberg dither to 4 greyscale levels."""
    arr = np.array(img.convert("L"), dtype=np.float32)
    h, w = arr.shape
    for y in range(h):
        for x in range(w):
            old      = arr[y, x]
            new      = LEVELS[np.argmin(np.abs(LEVELS - old))]
            arr[y,x] = new
            err      = old - new
            if x+1 < w:           arr[y,   x+1] += err * 7/16
            if y+1 < h:
                if x-1 >= 0:      arr[y+1, x-1] += err * 3/16
                arr[y+1, x  ]    += err * 5/16
                if x+1 < w:       arr[y+1, x+1] += err * 1/16
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="L")


def process(src_path: str, dst_path: str):
    img = Image.open(src_path).convert("RGB")

    # Resize to fit PHOTO_W × PHOTO_H — crop to fill, no letterboxing
    src_ratio = img.width / img.height
    tgt_ratio = PHOTO_W / PHOTO_H
    if src_ratio > tgt_ratio:
        # image is wider than target — fit height, crop width
        new_h = PHOTO_H
        new_w = int(new_h * src_ratio)
    else:
        # image is taller than target — fit width, crop height
        new_w = PHOTO_W
        new_h = int(new_w / src_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Centre crop to exact target size
    left = (new_w - PHOTO_W) // 2
    top  = (new_h - PHOTO_H) // 2
    img  = img.crop((left, top, left + PHOTO_W, top + PHOTO_H))

    dithered = dither(img)
    dithered.save(dst_path, format="BMP")


def main():
    if not os.path.isdir(RAW_DIR):
        print(f"Raw photos folder not found: {RAW_DIR}")
        print("Create it and drop your photos in there, then re-run.")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)

    # Collect all supported image files, sorted by filename
    files = sorted([
        f for f in os.listdir(RAW_DIR)
        if os.path.splitext(f)[1].lower() in EXTS
    ])

    if not files:
        print(f"No images found in {RAW_DIR}")
        print(f"Supported formats: {', '.join(EXTS)}")
        sys.exit(1)

    print(f"Found {len(files)} image(s) in {RAW_DIR}")
    print(f"Output → {OUT_DIR}")
    print()

    # Clear old BMPs so numbering is always clean
    for old in os.listdir(OUT_DIR):
        if old.endswith(".bmp"):
            os.remove(os.path.join(OUT_DIR, old))

    for i, filename in enumerate(files, start=1):
        src = os.path.join(RAW_DIR, filename)
        dst = os.path.join(OUT_DIR, f"{i:03d}.bmp")
        print(f"  [{i:03d}] {filename} → {os.path.basename(dst)}", end="", flush=True)
        try:
            process(src, dst)
            print("  ✓")
        except Exception as e:
            print(f"  ✗ ERROR: {e}")

    total = len([f for f in os.listdir(OUT_DIR) if f.endswith(".bmp")])
    print(f"\nDone. {total} BMPs ready in backend/photos/")
    print()
    print("To copy to server:")
    print("  scp ~/Desktop/pico-eink-display/backend/photos/*.bmp cribbbserver:~/pico-eink-display/backend/photos/")

if __name__ == "__main__":
    main()
