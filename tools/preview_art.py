import httpx, sys, tempfile, subprocess

API_BASE = "http://100.84.37.35:8765"

def main():
    print("Fetching /status ...")
    resp = httpx.get(f"{API_BASE}/status", timeout=10)
    resp.raise_for_status()
    data = resp.json()

    spotify  = data.get("spotify", {})
    track_id = spotify.get("track_id")
    track    = spotify.get("track", "Unknown")
    artist   = spotify.get("artist", "Unknown")

    if not track_id or not spotify.get("is_playing"):
        print("❌ Nothing is playing right now. Start Spotify and try again.")
        sys.exit(1)

    print(f"🎵 Now playing: {track} — {artist}")
    print(f"   track_id: {track_id}")
    print("Fetching /art/{track_id} ...")
    art_resp = httpx.get(f"{API_BASE}/art/{track_id}", timeout=15)
    art_resp.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as f:
        f.write(art_resp.content)
        tmp_path = f.name

    print(f"✅ BMP saved to {tmp_path} ({len(art_resp.content)} bytes)")
    print("Opening in Preview ...")
    subprocess.run(["open", tmp_path])

if __name__ == "__main__":
    main()
