"""
Unified weather fetcher.
- US cities  → NOAA weather.gov (most accurate for US)
- All others → Open-Meteo (free, global, no API key)
City names come dynamically from Polymarket — we geocode them on the fly.
"""

import asyncio
import logging
import aiohttp
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from config import (NOAA_API_BASE, NOAA_USER_AGENT,
                    OPEN_METEO_API, OPEN_METEO_GEO_API, US_CITY_KEYWORDS)

logger = logging.getLogger(__name__)

NOAA_HEADERS = {"User-Agent": NOAA_USER_AGENT, "Accept": "application/geo+json"}

# Cache geocoding results so we don't repeat API calls
_geo_cache: dict[str, Optional[tuple[float, float]]] = {}
# Cache NOAA grid points
_grid_cache: dict[str, Optional[str]] = {}


@dataclass
class CityForecast:
    city:        str
    high_c:      Optional[float]   # Celsius (canonical)
    low_c:       Optional[float]
    high_f:      Optional[float]   # Fahrenheit
    low_f:       Optional[float]
    description: str
    source:      str               # "NOAA" or "Open-Meteo"
    forecast_date: date

    def temp_str(self) -> str:
        parts = []
        if self.high_f is not None:
            parts.append(f"High {self.high_f:.0f}°F / {self.high_c:.1f}°C")
        if self.low_f is not None:
            parts.append(f"Low {self.low_f:.0f}°F / {self.low_c:.1f}°C")
        return " · ".join(parts)


def c_to_f(c: float) -> float:
    return round(c * 9 / 5 + 32, 1)

def f_to_c(f: float) -> float:
    return round((f - 32) * 5 / 9, 1)

def is_us_city(city_name: str) -> bool:
    name = city_name.lower()
    return any(kw in name for kw in US_CITY_KEYWORDS)


# ── Geocoding ─────────────────────────────────────────────────────────────────

async def geocode(session: aiohttp.ClientSession,
                  city: str) -> Optional[tuple[float, float]]:
    """Resolve city name → (lat, lon) using Open-Meteo geocoding."""
    if city in _geo_cache:
        return _geo_cache[city]

    try:
        async with session.get(
            OPEN_METEO_GEO_API,
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            if r.status == 200:
                data    = await r.json()
                results = data.get("results", [])
                if results:
                    lat = results[0]["latitude"]
                    lon = results[0]["longitude"]
                    _geo_cache[city] = (lat, lon)
                    logger.debug(f"📍 Geocoded {city} → ({lat}, {lon})")
                    return (lat, lon)
    except Exception as e:
        logger.error(f"Geocode failed for {city}: {e}")

    _geo_cache[city] = None
    return None


# ── NOAA (US cities) ──────────────────────────────────────────────────────────

async def noaa_grid(session, lat: float, lon: float) -> Optional[str]:
    key = f"{lat},{lon}"
    if key in _grid_cache:
        return _grid_cache[key]
    try:
        async with session.get(
            f"{NOAA_API_BASE}/points/{lat},{lon}",
            headers=NOAA_HEADERS, timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            if r.status == 200:
                data = await r.json()
                url  = data.get("properties", {}).get("forecast")
                _grid_cache[key] = url
                return url
    except Exception as e:
        logger.error(f"NOAA grid error: {e}")
    _grid_cache[key] = None
    return None


async def fetch_noaa(session, city: str, lat: float, lon: float) -> Optional[CityForecast]:
    forecast_url = await noaa_grid(session, lat, lon)
    if not forecast_url:
        return None
    try:
        async with session.get(forecast_url, headers=NOAA_HEADERS,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return None
            data    = await r.json()
            periods = data.get("properties", {}).get("periods", [])
            today   = date.today()

            high_f = low_f = None
            desc = ""
            for p in periods:
                pdate = datetime.fromisoformat(p.get("startTime", "")[:10]).date()
                if pdate != today:
                    continue
                temp = p.get("temperature")
                if p.get("isDaytime") and temp is not None:
                    high_f = float(temp)
                    desc   = p.get("shortForecast", "")
                elif not p.get("isDaytime") and temp is not None:
                    low_f = float(temp)

            if high_f is None:
                for p in periods[:4]:
                    if p.get("isDaytime"):
                        high_f = float(p["temperature"])
                        desc   = p.get("shortForecast", "")
                        break

            if high_f is None:
                return None

            return CityForecast(
                city=city, high_f=high_f, low_f=low_f,
                high_c=f_to_c(high_f), low_c=f_to_c(low_f) if low_f else None,
                description=desc, source="NOAA", forecast_date=today,
            )
    except Exception as e:
        logger.error(f"NOAA fetch failed for {city}: {e}")
    return None


# ── Open-Meteo (international) ────────────────────────────────────────────────

async def fetch_open_meteo(session, city: str,
                           lat: float, lon: float) -> Optional[CityForecast]:
    try:
        async with session.get(
            OPEN_METEO_API,
            params={
                "latitude":        lat,
                "longitude":       lon,
                "daily":           "temperature_2m_max,temperature_2m_min,weathercode",
                "timezone":        "auto",
                "forecast_days":   2,
            },
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            if r.status != 200:
                return None
            data  = await r.json()
            daily = data.get("daily", {})

            dates  = daily.get("time", [])
            highs  = daily.get("temperature_2m_max", [])
            lows   = daily.get("temperature_2m_min", [])
            codes  = daily.get("weathercode", [])

            today_str = str(date.today())
            idx = next((i for i, d in enumerate(dates) if d == today_str), None)
            if idx is None:
                return None

            high_c = highs[idx]
            low_c  = lows[idx]
            code   = codes[idx] if idx < len(codes) else 0
            desc   = wmo_description(code)

            return CityForecast(
                city=city, high_c=high_c, low_c=low_c,
                high_f=c_to_f(high_c), low_f=c_to_f(low_c),
                description=desc, source="Open-Meteo", forecast_date=date.today(),
            )
    except Exception as e:
        logger.error(f"Open-Meteo fetch failed for {city}: {e}")
    return None


def wmo_description(code: int) -> str:
    """Convert WMO weather code to human-readable string."""
    mapping = {
        0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
        45: "Foggy", 48: "Icy Fog",
        51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
        61: "Slight Rain", 63: "Rain", 65: "Heavy Rain",
        71: "Slight Snow", 73: "Snow", 75: "Heavy Snow",
        80: "Rain Showers", 81: "Heavy Rain Showers", 82: "Violent Rain Showers",
        85: "Snow Showers", 86: "Heavy Snow Showers",
        95: "Thunderstorm", 96: "Thunderstorm w/ Hail", 99: "Heavy Thunderstorm",
    }
    return mapping.get(code, f"Code {code}")


# ── Unified fetcher ───────────────────────────────────────────────────────────

async def fetch_forecast(session, city: str) -> Optional[CityForecast]:
    """Fetch forecast for any city — routes to NOAA or Open-Meteo automatically."""
    coords = await geocode(session, city)
    if not coords:
        logger.warning(f"Could not geocode: {city}")
        return None

    lat, lon = coords

    if is_us_city(city):
        forecast = await fetch_noaa(session, city, lat, lon)
        if forecast:
            logger.info(f"✅ NOAA  {city}: {forecast.temp_str()} — {forecast.description}")
            return forecast
        # Fallback to Open-Meteo if NOAA fails
        logger.warning(f"NOAA failed for {city}, falling back to Open-Meteo")

    forecast = await fetch_open_meteo(session, city, lat, lon)
    if forecast:
        logger.info(f"✅ Open-Meteo {city}: {forecast.temp_str()} — {forecast.description}")
    return forecast


async def fetch_forecasts_for_cities(cities: list[str]) -> dict[str, CityForecast]:
    """Fetch forecasts for all cities concurrently."""
    results = {}
    async with aiohttp.ClientSession() as session:
        tasks = {city: fetch_forecast(session, city) for city in cities}
        fetched = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for city, result in zip(tasks.keys(), fetched):
            if isinstance(result, CityForecast):
                results[city] = result
            else:
                logger.warning(f"❌ Forecast failed for {city}: {result}")
    return results
