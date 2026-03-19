"""
NOAA weather.gov API integration.
Fetches high/low temperature forecasts for each city.
No API key required — completely free.
"""

import asyncio
import logging
import aiohttp
from datetime import datetime, date, timedelta
from typing import Optional
from config import NOAA_API_BASE, NOAA_USER_AGENT

logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": NOAA_USER_AGENT, "Accept": "application/geo+json"}


class NOAAForecast:
    def __init__(self, city: str, forecast_date: date,
                 high_f: Optional[float], low_f: Optional[float],
                 description: str):
        self.city          = city
        self.forecast_date = forecast_date
        self.high_f        = high_f
        self.low_f         = low_f
        self.description   = description

    def __repr__(self):
        return (f"NOAAForecast({self.city}, {self.forecast_date}, "
                f"high={self.high_f}°F, low={self.low_f}°F)")


async def get_noaa_grid(session: aiohttp.ClientSession,
                        lat: float, lon: float) -> Optional[dict]:
    """Resolve lat/lon → NOAA grid point."""
    url = f"{NOAA_API_BASE}/points/{lat},{lon}"
    try:
        async with session.get(url, headers=HEADERS,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                data  = await r.json()
                props = data.get("properties", {})
                return {
                    "forecast_url": props.get("forecast"),
                    "office":       props.get("gridId"),
                }
    except Exception as e:
        logger.error(f"NOAA grid lookup failed for {lat},{lon}: {e}")
    return None


async def get_city_forecast(session: aiohttp.ClientSession,
                            city_name: str, lat: float, lon: float,
                            days_ahead: int = 0) -> Optional[NOAAForecast]:
    """Fetch NOAA high/low forecast for a city."""
    grid = await get_noaa_grid(session, lat, lon)
    if not grid or not grid.get("forecast_url"):
        logger.warning(f"Could not resolve NOAA grid for {city_name}")
        return None

    try:
        async with session.get(grid["forecast_url"], headers=HEADERS,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return None

            data    = await r.json()
            periods = data.get("properties", {}).get("periods", [])
            target  = date.today() + timedelta(days=days_ahead)

            high_f, low_f, desc = None, None, ""

            for period in periods:
                pdate = datetime.fromisoformat(period.get("startTime", "")[:10]).date()
                if pdate != target:
                    continue
                temp = period.get("temperature")
                if period.get("isDaytime") and temp is not None:
                    high_f = float(temp)
                    desc   = period.get("shortForecast", "")
                elif not period.get("isDaytime") and temp is not None:
                    low_f = float(temp)

            # fallback: first daytime period
            if high_f is None:
                for p in periods[:4]:
                    if p.get("isDaytime"):
                        high_f = float(p["temperature"])
                        desc   = p.get("shortForecast", "")
                        break

            if high_f is None and low_f is None:
                return None

            return NOAAForecast(city_name, target, high_f, low_f, desc)

    except Exception as e:
        logger.error(f"NOAA forecast fetch failed for {city_name}: {e}")
        return None


async def fetch_all_cities(cities: dict, days_ahead: int = 0) -> dict:
    """Fetch forecasts for all cities concurrently."""
    results = {}
    async with aiohttp.ClientSession() as session:
        tasks = {
            name: get_city_forecast(session, name, info["lat"], info["lon"], days_ahead)
            for name, info in cities.items()
        }
        forecasts = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for name, forecast in zip(tasks.keys(), forecasts):
            if isinstance(forecast, NOAAForecast):
                results[name] = forecast
                logger.info(f"✅ NOAA {name}: high={forecast.high_f}°F low={forecast.low_f}°F — {forecast.description}")
            else:
                logger.warning(f"❌ NOAA failed for {name}: {forecast}")
    return results
