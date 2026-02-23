import httpx
import time

MOCK_MODE = False

_token_cache = {
    "access_token": None,
    "expires_at":   0,
}

# Maps track_id → Spotify CDN art URL
# Populated on every get_now_playing() call in real mode
# Used by /art/{track_id} endpoint to fetch + process the image
_art_url_store: dict[str, str] = {}


MOCK_PLAYING = {
    "is_playing": True,
    "track":      "Pyramid Song",
    "artist":     "Radiohead",
    "album":      "Amnesiac",
    "track_id":   "mock_track_001",
    "art_url":    "/art/mock_track_001",
}

MOCK_IDLE = {
    "is_playing": False,
    "track":      None,
    "artist":     None,
    "album":      None,
    "track_id":   None,
    "art_url":    None,
}

MOCK_IS_PLAYING = True


def get_stored_art_url(track_id: str) -> str | None:
    """Look up the Spotify CDN art URL for a given track_id."""
    return _art_url_store.get(track_id)


async def get_now_playing() -> dict:
    if MOCK_MODE:
        return MOCK_PLAYING if MOCK_IS_PLAYING else MOCK_IDLE

    token = await _get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.spotify.com/v1/me/player/currently-playing",
            headers=headers,
            timeout=5,
        )

    if resp.status_code == 204:
        return MOCK_IDLE

    resp.raise_for_status()
    data = resp.json()

    if not data or not data.get("item"):
        return MOCK_IDLE

    track    = data["item"]
    artists  = ", ".join(a["name"] for a in track["artists"])
    images   = track["album"]["images"]
    track_id = track["id"]

    # Store the art URL so /art/{track_id} can fetch it later
    if images:
        _art_url_store[track_id] = images[0]["url"]  # largest image first

    return {
        "is_playing": data.get("is_playing", False),
        "track":      track["name"],
        "artist":     artists,
        "album":      track["album"]["name"],
        "track_id":   track_id,
        "art_url":    f"/art/{track_id}",
    }


async def _get_access_token() -> str:
    if time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]

    from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN
    import base64

    credentials = base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":    "refresh_token",
                "refresh_token": SPOTIFY_REFRESH_TOKEN,
            },
            timeout=10,
        )
        resp.raise_for_status()
        token_data = resp.json()

    _token_cache["access_token"] = token_data["access_token"]
    _token_cache["expires_at"]   = time.time() + token_data["expires_in"]

    return _token_cache["access_token"]
