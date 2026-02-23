"""
One-time script to get a Spotify refresh token.
Run on any machine with Python 3 and a browser.

Steps:
  1. Run this script — it prints an authorization URL
  2. Open that URL in your browser and log in / approve
  3. Spotify redirects to https://localhost:9999/callback?code=XXXX
     (the page won't load — that's fine)
  4. Copy the full URL from your browser's address bar
  5. Paste it into the prompt here
  6. Script prints your refresh token
"""

import urllib.parse
import httpx
import base64

CLIENT_ID     = "2d32ddd3acf14db6b201cd5b1197dcca"
CLIENT_SECRET = "ca9c7c1b30d648c5976f7fe0f9a6eac0"
REDIRECT_URI  = "https://localhost:9999/callback"

# Scopes we need:
#   user-read-currently-playing  — see what's playing
#   user-read-playback-state     — see is_playing flag
SCOPES = "user-read-currently-playing user-read-playback-state"

# ── Step 1: Build the authorization URL ──────────────────────────
params = {
    "client_id":     CLIENT_ID,
    "response_type": "code",
    "redirect_uri":  REDIRECT_URI,
    "scope":         SCOPES,
}
auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)

print("\n─────────────────────────────────────────────────")
print("Open this URL in your browser:\n")
print(auth_url)
print("\n─────────────────────────────────────────────────")
print("After approving, your browser will fail to load a page.")
print("Copy the FULL URL from the address bar and paste it below.")
print("─────────────────────────────────────────────────\n")

# ── Step 2: Get the code from the redirected URL ──────────────────
redirected = input("Paste the full redirected URL here: ").strip()
parsed     = urllib.parse.urlparse(redirected)
code       = urllib.parse.parse_qs(parsed.query).get("code", [None])[0]

if not code:
    print("\n❌ Could not find 'code' in that URL. Did you copy the full address bar URL?")
    exit(1)

print(f"\n✔  Got authorization code: {code[:20]}...")

# ── Step 3: Exchange code for tokens ─────────────────────────────
credentials = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

resp = httpx.post(
    "https://accounts.spotify.com/api/token",
    headers={
        "Authorization": f"Basic {credentials}",
        "Content-Type":  "application/x-www-form-urlencoded",
    },
    data={
        "grant_type":   "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
    },
)

if resp.status_code != 200:
    print(f"\n❌ Token exchange failed: {resp.status_code}")
    print(resp.text)
    exit(1)

tokens = resp.json()

print("\n─────────────────────────────────────────────────")
print("✅ SUCCESS — copy your refresh token below:\n")
print(f"SPOTIFY_REFRESH_TOKEN={tokens['refresh_token']}")
print("\n─────────────────────────────────────────────────")
print("Add this to your ~/pico-eink-display/.env file.")
