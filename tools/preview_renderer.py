"""
preview_renderer.py — Run on your Mac to preview both screens.

Usage:
    ~/miniforge3/bin/python3 ~/Desktop/pico-eink-display/tools/preview_renderer.py
"""

import sys, os, subprocess, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.renderer import render_idle, render_now_playing
from PIL import Image
import numpy as np

MOCK_STATUS = {
    "time": "14:32",
    "date": "Thu 19 Feb",
    "weather": {
        "temp_c": 8,
        "condition": "drizzle",
        "forecast": [
            {"hour": "15:00", "temp_c": 7,  "condition": "drizzle"},
            {"hour": "19:00", "temp_c": 5,  "condition": "rain"},
            {"hour": "23:00", "temp_c": 4,  "condition": "overcast"},
            {"hour": "03:00", "temp_c": 3,  "condition": "overcast"},
            {"hour": "07:00", "temp_c": 4,  "condition": "partly_cloudy"},
            {"hour": "11:00", "temp_c": 8,  "condition": "sunny"},
        ]
    },
    "spotify": {
        "is_playing": True,
        "track": "Pyramid Song",
        "artist": "Radiohead",
        "album": "Amnesiac",
        "track_id": "abc123",
        "art_url": "/art/abc123"
    }
}

def _placeholder_art():
    arr = np.zeros((280,280), dtype=np.uint8)
    for y in range(280):
        for x in range(280):
            arr[y,x] = int((x/280)*200 + (y/280)*55)
    img = Image.fromarray(arr, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()

def show(img, path):
    img.resize((img.width*2, img.height*2), Image.NEAREST).save(path)
    print(f"Saved: {path}")
    subprocess.run(["open", path])

if __name__ == "__main__":
    print("Rendering idle screen…")
    show(render_idle(MOCK_STATUS), "/tmp/preview_idle.png")
    print("Rendering now-playing screen…")
    show(render_now_playing(MOCK_STATUS, _placeholder_art()), "/tmp/preview_now_playing.png")
    print("\nDone. Edit MOCK_STATUS or constants in backend/renderer.py and re-run.")
