import os

# Spotify OAuth credentials
SPOTIFY_CLIENT_ID     = os.environ["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
SPOTIFY_REFRESH_TOKEN = os.environ["SPOTIFY_REFRESH_TOKEN"]

# Home location for weather (Winterthur area)
HOME_LAT = float(os.getenv("HOME_LAT", "47.48728357105892"))
HOME_LON = float(os.getenv("HOME_LON", "8.712626997793446"))

# How long to cache weather data (seconds)
WEATHER_CACHE_TTL = int(os.getenv("WEATHER_CACHE_TTL", "900"))  # 15 min
