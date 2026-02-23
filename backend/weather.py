import time
import datetime
import httpx
from config import HOME_LAT, HOME_LON, WEATHER_CACHE_TTL

_cache = {}

WMO_CODE_MAP = {
    0:  "sunny",
    1:  "mostly_sunny",
    2:  "partly_cloudy",
    3:  "overcast",
    45: "fog",
    48: "fog",
    51: "drizzle",
    53: "drizzle",
    55: "drizzle",
    61: "rain",
    63: "rain",
    65: "heavy_rain",
    71: "snow",
    73: "snow",
    75: "heavy_snow",
    80: "showers",
    81: "showers",
    82: "heavy_showers",
    95: "thunderstorm",
    96: "thunderstorm",
    99: "thunderstorm",
}

def _wmo_to_condition(code: int) -> str:
    return WMO_CODE_MAP.get(code, "unknown")


async def fetch_weather() -> dict:
    """
    Return weather data, using cache if still fresh.
    Uses MeteoSwiss ICON-CH2 model (2km resolution) via Open-Meteo.
    Forecast is 6 hourly slots, 4 hours apart, starting from the next full hour.
    """
    now = time.time()

    if _cache.get("data") and (now - _cache.get("fetched_at", 0)) < WEATHER_CACHE_TTL:
        return _cache["data"]

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={HOME_LAT}"
        f"&longitude={HOME_LON}"
        "&current=temperature_2m,weather_code"
        "&hourly=temperature_2m,weather_code"
        "&forecast_days=2"              # today + tomorrow covers any 24h window
        "&timezone=Europe%2FZurich"
        "&models=meteoswiss_icon_ch2"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
        raw = resp.json()

    current = raw["current"]
    hourly  = raw["hourly"]

    # hourly["time"] is a list of strings like "2026-02-20T14:00"
    # Find the index of the next full hour from now
    now_dt   = datetime.datetime.now(datetime.timezone.utc).astimezone(
                    datetime.timezone(datetime.timedelta(hours=1)))  # CET
    now_hour = now_dt.replace(minute=0, second=0, microsecond=0)
    next_hour = now_hour + datetime.timedelta(hours=1)

    # Find the index in the hourly array that matches next_hour
    start_idx = None
    for i, t_str in enumerate(hourly["time"]):
        t = datetime.datetime.fromisoformat(t_str).replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
        if t >= next_hour:
            start_idx = i
            break

    # Build 6 slots, 4 hours apart
    forecast = []
    if start_idx is not None:
        for step in range(6):
            idx = start_idx + step * 4
            if idx >= len(hourly["time"]):
                break
            t_str = hourly["time"][idx]          # e.g. "2026-02-20T15:00"
            hour_label = t_str[11:16]            # "15:00"
            forecast.append({
                "hour":      hour_label,
                "temp_c":    round(hourly["temperature_2m"][idx]),
                "condition": _wmo_to_condition(hourly["weather_code"][idx]),
            })

    data = {
        "temp_c":    round(current["temperature_2m"]),
        "condition": _wmo_to_condition(current["weather_code"]),
        "forecast":  forecast,
    }

    _cache["data"]       = data
    _cache["fetched_at"] = now

    return data
