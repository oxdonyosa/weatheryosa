"""
Polymarket — fetches directly from the weather section,
then matches each market against NOAA forecast temperature.
"""

import asyncio
import json
import logging
import re
import aiohttp
from dataclasses import dataclass
from typing import Optional
from config import POLYMARKET_GAMMA_API

logger = logging.getLogger(__name__)

# Polymarket weather section — try these in order until one returns data
WEATHER_ENDPOINTS = [
    f"{POLYMARKET_GAMMA_API}/events?tag=weather&active=true&closed=false&limit=100&offset=0",
    f"{POLYMARKET_GAMMA_API}/events?tag_slug=weather&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/markets?tag=weather&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/markets?tag_slug=weather&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/events?category=weather&active=true&closed=false&limit=100",
]

# Also try fetching the Polymarket website weather tag directly
POLYMARKET_WEB_API = "https://polymarket.com/api/events?tag=weather&active=true&limit=100"


@dataclass
class TemperatureBucket:
    market_id:   str
    question:    str
    outcome:     str
    yes_price:   float
    no_price:    float
    volume_usd:  float
    low_bound:   Optional[float]
    high_bound:  Optional[float]
    is_above:    bool
    is_below:    bool
    market_url:  str
    noaa_match:  bool = False   # Set to True when NOAA forecast hits this bucket


def parse_temp_range(text: str):
    """Parse a temperature bucket label into bounds."""
    t = text.replace("°F", "").replace("°", "").strip()

    above = re.search(r"(?:above|over|>\s*)\s*(\d+(?:\.\d+)?)", t, re.I)
    if not above:
        above = re.search(r"(\d+(?:\.\d+)?)\s*(?:or higher|or more|\+)", t, re.I)
    if above:
        return float(above.group(1)), None, True, False

    below = re.search(r"(?:below|under|<\s*)\s*(\d+(?:\.\d+)?)", t, re.I)
    if not below:
        below = re.search(r"(\d+(?:\.\d+)?)\s*(?:or lower|or less)", t, re.I)
    if below:
        return None, float(below.group(1)), False, True

    rng = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)", t)
    if rng:
        return float(rng.group(1)), float(rng.group(2)), False, False

    return None, None, False, False


def forecast_hits_bucket(temp: float, low, high, is_above, is_below) -> bool:
    """Returns True if NOAA forecast temperature falls inside this bucket."""
    if is_above and low is not None:
        return temp >= low
    if is_below and high is not None:
        return temp < high
    if low is not None and high is not None:
        return low <= temp < high
    return False


async def fetch_raw_weather_markets(session: aiohttp.ClientSession) -> list:
    """
    Hit the Polymarket weather section and return a flat list of market dicts.
    Tries multiple endpoint formats until one works.
    """
    for url in WEATHER_ENDPOINTS + [POLYMARKET_WEB_API]:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15),
                                   headers={"User-Agent": "Mozilla/5.0"}) as r:
                if r.status != 200:
                    logger.debug(f"❌ {r.status} from {url}")
                    continue

                data = await r.json(content_type=None)

                # Unwrap response envelope
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = (data.get("events")
                             or data.get("markets")
                             or data.get("data")
                             or data.get("results")
                             or [])
                else:
                    continue

                if not items:
                    continue

                # Flatten events → their nested markets
                flat = []
                for item in items:
                    nested = item.get("markets", [])
                    if nested:
                        # Carry parent event question down if market has none
                        for m in nested:
                            if not m.get("question"):
                                m["question"] = item.get("title") or item.get("question", "")
                        flat.extend(nested)
                    else:
                        flat.append(item)

                logger.info(f"✅ Polymarket weather section: {len(flat)} markets from {url}")
                return flat

        except Exception as e:
            logger.debug(f"Endpoint failed {url}: {e}")

    logger.warning("⚠️ Could not fetch Polymarket weather section from any endpoint.")
    return []


def extract_buckets(mkt: dict, city_terms: list) -> list:
    """
    Given a raw market dict and a city's search terms,
    return matching TemperatureBucket objects.
    """
    question = mkt.get("question") or mkt.get("title") or ""
    q_lower  = question.lower()

    # City match
    if not any(t.lower() in q_lower for t in city_terms):
        return []

    # Temperature market check
    temp_keywords = ["temperature", "degrees", "°", "high temp", "low temp"]
    if not any(kw in q_lower for kw in temp_keywords):
        return []

    mid    = mkt.get("id") or mkt.get("conditionId") or "unknown"
    slug   = mkt.get("slug") or mkt.get("marketSlug") or str(mid)
    volume = float(mkt.get("volume") or mkt.get("volumeNum") or 0)
    url    = f"https://polymarket.com/event/{slug}"

    outcomes   = mkt.get("outcomes", [])
    out_prices = mkt.get("outcomePrices", [])

    if isinstance(outcomes, str):
        try:   outcomes = json.loads(outcomes)
        except: outcomes = []
    if isinstance(out_prices, str):
        try:   out_prices = json.loads(out_prices)
        except: out_prices = []

    # Fallback: tokens array format
    if not outcomes:
        for token in mkt.get("tokens", []):
            outcomes.append(token.get("outcome", ""))
            out_prices.append(token.get("price", 0.5))

    buckets = []
    for i, outcome in enumerate(outcomes):
        yes_price = float(out_prices[i]) if i < len(out_prices) else 0.5
        low, high, is_above, is_below = parse_temp_range(str(outcome))
        buckets.append(TemperatureBucket(
            market_id  = f"{mid}_{i}",
            question   = question,
            outcome    = str(outcome),
            yes_price  = yes_price,
            no_price   = 1.0 - yes_price,
            volume_usd = volume,
            low_bound  = low,
            high_bound = high,
            is_above   = is_above,
            is_below   = is_below,
            market_url = url,
        ))
    return buckets


def match_buckets_with_noaa(buckets: list, forecast_high: float) -> list:
    """
    Tag each bucket with whether the NOAA forecast hits it.
    This is the core accuracy layer — NOAA tells us which bucket
    SHOULD resolve YES, so we know which prices are wrong.
    """
    for bucket in buckets:
        bucket.noaa_match = forecast_hits_bucket(
            forecast_high,
            bucket.low_bound,
            bucket.high_bound,
            bucket.is_above,
            bucket.is_below,
        )
    return buckets


async def fetch_all_city_markets(cities: dict) -> dict:
    """
    Fetch weather section ONCE, then split by city and match with NOAA.
    Much more efficient than searching per city.
    """
    results = {city: [] for city in cities}

    async with aiohttp.ClientSession() as session:
        all_markets = await fetch_raw_weather_markets(session)

    if not all_markets:
        logger.warning("No weather markets returned from Polymarket.")
        return results

    # Filter and sort into cities
    for city, info in cities.items():
        city_buckets = []
        for mkt in all_markets:
            buckets = extract_buckets(mkt, info["search_terms"])
            city_buckets.extend(buckets)

        results[city] = city_buckets
        if city_buckets:
            logger.info(f"📈 {city}: {len(city_buckets)} temperature buckets found")
        else:
            logger.info(f"💤 {city}: no temperature markets active right now")

    return results
