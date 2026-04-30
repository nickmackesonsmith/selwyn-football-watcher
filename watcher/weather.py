"""
Weather forecast via Open-Meteo.
Free, no API key, no rate limits.
Fetches the hourly forecast for a specific lat/lng and hour.
"""

import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather code → plain English description
WMO_DESCRIPTIONS = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "cloudy",
    45: "fog",
    48: "fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "light freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "showers",
    81: "showers",
    82: "heavy showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "thunderstorms with hail",
}

WIND_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _wind_direction(degrees: float) -> str:
    """Convert wind direction in degrees to 8-point compass label."""
    idx = round(degrees / 45) % 8
    return WIND_DIRECTIONS[idx]


def _wind_descriptor(speed_kmh: float) -> str:
    """Describe wind speed in plain English."""
    if speed_kmh < 15:
        return "light"
    elif speed_kmh < 30:
        return "moderate"
    else:
        return "strong"


def get_forecast_line(lat: float, lng: float, kickoff: datetime) -> str:
    """
    Fetch the weather forecast for the given location at the kick-off hour.

    Returns a one-line string like:
        "14°C, partly cloudy, 20% chance of rain, light SW wind"
    Or an empty string if the forecast cannot be retrieved.
    """
    try:
        params = {
            "latitude": lat,
            "longitude": lng,
            "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m,wind_direction_10m",
            "timezone": "Pacific/Auckland",
            "forecast_days": 7,
        }
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        precip_probs = hourly.get("precipitation_probability", [])
        weather_codes = hourly.get("weather_code", [])
        wind_speeds = hourly.get("wind_speed_10m", [])
        wind_dirs = hourly.get("wind_direction_10m", [])

        # Find the index matching the kick-off hour
        target = kickoff.strftime("%Y-%m-%dT%H:00")
        if target not in times:
            logger.warning("Kick-off hour %s not in forecast times", target)
            return ""

        idx = times.index(target)
        temp = temps[idx]
        precip = precip_probs[idx] if precip_probs else 0
        wmo = int(weather_codes[idx]) if weather_codes else 0
        wind_spd = wind_speeds[idx] if wind_speeds else 0
        wind_dir_deg = wind_dirs[idx] if wind_dirs else 0

        condition = WMO_DESCRIPTIONS.get(wmo, "variable")
        wind_desc = _wind_descriptor(wind_spd)
        wind_dir_label = _wind_direction(wind_dir_deg)

        # Build rain phrase
        if precip > 60:
            rain_phrase = f"rain likely ({int(precip)}%), bring a change of kit"
        elif precip > 0:
            rain_phrase = f"{int(precip)}% chance of rain"
        else:
            rain_phrase = None

        parts = [f"{int(round(temp))}°C", condition]
        if rain_phrase:
            parts.append(rain_phrase)
        parts.append(f"{wind_desc} {wind_dir_label} wind")

        return ", ".join(parts)

    except Exception as exc:
        logger.warning("Weather forecast failed: %s", exc)
        return ""
