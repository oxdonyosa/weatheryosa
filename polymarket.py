"""
Polymarket — fetches ALL active markets from the weather section dynamically.
Cities are NOT hardcoded — we extract them from market titles.
"""

import asyncio
import json
import logging
import re
import aiohttp
from dataclasses import dataclass, field
from typing import Optional
from config import POLYMARKET_GAMMA_API, POLYMARKET_WEB_URL

logger = logging.getLogger(__name__)

# Polymarket weather section endpoints — try in order
WEATHER_ENDPOINTS = [
    f"{POLYMARKET_GAMMA_API}/events?tag=weather&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/events?tag_slug=weather&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/markets?tag=weather&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/markets?category=weather&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/events?category=weather&active=true&closed=false&limit=100",
]


@dataclass
class TemperatureBucket:
    market_id:   str
    city:        str           # Extracted from market title
    question:    str
    outcome:     str
    yes_price:   float
    volume_usd:  float
    low_bound:   Optional[float]
    high_bound:  Optional[float]
    is_above:    bool
    is_below:    bool
    is_celsius:  bool          # True if market uses °C
    market_url:  str
    noaa_match:  bool = field(default=False)   # Set by signal engine


def parse_temp_range(text: str):
    """Parse bucket label → (low, high, is_above, is_below, is_celsius)."""
    is_c = "°C" in text or ("°F" not in text and re.search(r"\b\d{1,2}\b", text) and
                             not re.search(r"\b[5-9]\d\b|\b1[0-1]\d\b", text))
    t    = text.replace("°F", "").replace("°C", "").replace("°", "").strip()

    above = re.search(r"(?:above|over|>\s*)\s*(\d+(?:\.\d+)?)", t, re.I)
    if not above:
        above = re.search(r"(\d+(?:\.\d+)?)\s*(?:or higher|or more|\+)", t, re.I)
    if above:
        return float(above.group(1)), None, True, False, is_c

    below = re.search(r"(?:below|under|<\s*)\s*(\d+(?:\.\d+)?)", t, re.I)
    if not below:
        below = re.search(r"(\d+(?:\.\d+)?)\s*(?:or lower|or less)", t, re.I)
    if below:
        return None, float(below.group(1)), False, True, is_c

    rng = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)", t)
    if rng:
        return float(rng.group(1)), float(rng.group(2)), False, False, is_c

    single = re.match(r"^(\d+(?:\.\d+)?)$", t.strip())
    if single:
        v = float(single.group(1))
        return v, v, False, False, is_c

    return None, None, False, False, is_c


def forecast_hits_bucket(temp_c: float, temp_f: float,
                          low, high, is_above, is_below,
                          is_celsius: bool) -> bool:
    """Check if forecast temperature falls in this bucket (handles °C and °F)."""
    temp = temp_c if is_celsius else temp_f

    if is_above and low is not None:
        return temp >= low
    if is_below and high is not None:
        return temp < high
    if low is not None and high is not None:
        return low <= temp <= high
    return False


def extract_city_from_question(question: str) -> Optional[str]:
    """Pull city name from 'Highest temperature in <City> on ...'"""
    m = re.search(r"(?:temperature in|temp in|weather in)\s+([^?on]+?)(?:\s+on\s+|\?|$)",
                  question, re.I)
    if m:
        return m.group(1).strip()
    # Fallback: look for "in <City>" pattern
    m2 = re.search(r"\bin\s+([A-Z][a-zA-Z\s]+?)(?:\s+on|\?|$)", question)
    if m2:
        return m2.group(1).strip()
    return None


def parse_market_to_buckets(mkt: dict) -> list[TemperatureBucket]:
    """Convert a raw Polymarket market dict → list of TemperatureBucket."""
    question = mkt.get("question") or mkt.get("title") or ""
    if not question:
        return []

    # Only temperature/weather markets
    q_lower = question.lower()
    if not any(kw in q_lower for kw in ["temperature", "temp", "°", "degrees"]):
        return []
    if "highest temperature" not in q_lower and "temperature" not in q_lower:
        return []

    city = extract_city_from_question(question)
    if not city:
        return []

    mid    = mkt.get("id") or mkt.get("conditionId") or "unknown"
    slug   = mkt.get("slug") or mkt.get("marketSlug") or str(mid)
    volume = float(mkt.get("volume") or mkt.get("volumeNum") or 0)
    url    = f"{POLYMARKET_WEB_URL}/event/{slug}"

    outcomes   = mkt.get("outcomes", [])
    out_prices = mkt.get("outcomePrices", [])

    if isinstance(outcomes, str):
        try:   outcomes = json.loads(outcomes)
        except: outcomes = []
    if isinstance(out_prices, str):
        try:   out_prices = json.loads(out_prices)
        except: out_prices = []

    if not outcomes:
        for token in mkt.get("tokens", []):
            outcomes.append(token.get("outcome", ""))
            out_prices.append(token.get("price", 0.5))

    buckets = []
    for i, outcome in enumerate(outcomes):
        yes_price = float(out_prices[i]) if i < len(out_prices) else 0.5
        low, high, is_above, is_below, is_c = parse_temp_range(str(outcome))
        buckets.append(TemperatureBucket(
            market_id  = f"{mid}_{i}",
            city       = city,
            question   = question,
            outcome    = str(outcome),
            yes_price  = yes_price,
            volume_usd = volume,
            low_bound  = low,
            high_bound = high,
            is_above   = is_above,
            is_below   = is_below,
            is_celsius = is_c,
            market_url = url,
        ))
    return buckets


async def fetch_polymarket_weather_section() -> dict[str, list[TemperatureBucket]]:
    """
    Fetch ALL markets from Polymarket weather section in one shot.
    Returns dict: city_name → list of TemperatureBucket
    Cities are extracted dynamically from market titles — no hardcoding.
    """
    raw_markets = []

    async with aiohttp.ClientSession() as session:
        for url in WEATHER_ENDPOINTS:
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers={"User-Agent": "Mozilla/5.0"}
                ) as r:
                    if r.status != 200:
                        logger.debug(f"❌ {r.status} — {url}")
                        continue

                    data = await r.json(content_type=None)

                    if isinstance(data, list):
                        items = data
                    elif isinstance(data, dict):
                        items = (data.get("events") or data.get("markets")
                                 or data.get("data") or data.get("results") or [])
                    else:
                        continue

                    if not items:
                        continue

                    # Flatten: events contain nested markets
                    for item in items:
                        nested = item.get("markets", [])
                        if nested:
                            for m in nested:
                                if not m.get("question"):
                                    m["question"] = item.get("title") or item.get("question", "")
                            raw_markets.extend(nested)
                        else:
                            raw_markets.append(item)

                    logger.info(f"✅ Polymarket weather section: {len(raw_markets)} raw markets from {url}")
                    break

            except Exception as e:
                logger.debug(f"Endpoint error {url}: {e}")

    if not raw_markets:
        logger.warning("⚠️ No markets fetched from Polymarket weather section.")
        return {}

    # Parse all markets → buckets, grouped by city
    city_markets: dict[str, list[TemperatureBucket]] = {}
    for mkt in raw_markets:
        buckets = parse_market_to_buckets(mkt)
        for b in buckets:
            city_markets.setdefault(b.city, []).append(b)

    cities_found = list(city_markets.keys())
    logger.info(f"🌍 Cities found in Polymarket weather section: {cities_found}")
    return city_markets
