"""
Polymarket — fetches directly from the temperature sub-category
under the weather section. Paginates to get all markets.
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

# Temperature sub-category endpoints — tried in order
# "temperature" is the sub-tag under "weather" on Polymarket
TEMPERATURE_ENDPOINTS = [
    f"{POLYMARKET_GAMMA_API}/events?tag=temperature&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/events?tag_slug=temperature&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/markets?tag=temperature&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/events?category=temperature&active=true&closed=false&limit=100",
    # Fallback: full weather category but filter client-side for temperature
    f"{POLYMARKET_GAMMA_API}/events?tag=weather&active=true&closed=false&limit=100",
]

# How to detect a temperature market vs other weather (wind, rain, etc.)
TEMP_KEYWORDS = ["temperature", "temp", "°f", "°c", "degrees", "highest temp", "high temp"]


@dataclass
class TemperatureBucket:
    market_id:   str
    city:        str
    question:    str
    outcome:     str
    yes_price:   float
    volume_usd:  float
    low_bound:   Optional[float]
    high_bound:  Optional[float]
    is_above:    bool
    is_below:    bool
    is_celsius:  bool
    market_url:  str
    noaa_match:  bool = field(default=False)


def parse_temp_range(text: str):
    is_c = "°c" in text.lower() or (
        "°f" not in text.lower() and
        bool(re.search(r"\b[0-9]{1,2}\b", text)) and
        not bool(re.search(r"\b[5-9]\d\b|\b1[0-1]\d\b", text))
    )
    t = re.sub(r"°[fFcC]|°", "", text).strip()

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
    temp = temp_c if is_celsius else temp_f
    if is_above and low is not None:
        return temp >= low
    if is_below and high is not None:
        return temp < high
    if low is not None and high is not None:
        return low <= temp <= high
    return False


def extract_city(question: str) -> Optional[str]:
    """Extract city from 'Highest temperature in <City> on ...'"""
    patterns = [
        r"(?:highest\s+)?temperature\s+in\s+([A-Za-z\s]+?)(?:\s+on\s+|\?|$)",
        r"(?:highest\s+)?temp\s+in\s+([A-Za-z\s]+?)(?:\s+on\s+|\?|$)",
        r"\bin\s+([A-Z][a-zA-Z\s]+?)(?:\s+on\s+|\?|$)",
    ]
    for pat in patterns:
        m = re.search(pat, question, re.I)
        if m:
            city = m.group(1).strip().rstrip("?").strip()
            if 2 < len(city) < 40:
                return city
    return None


def is_temperature_market(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in TEMP_KEYWORDS)


def parse_market(mkt: dict, parent_question: str = "") -> list[TemperatureBucket]:
    question = mkt.get("question") or mkt.get("title") or parent_question or ""
    if not question or not is_temperature_market(question):
        return []

    city = extract_city(question)
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

    # Fallback: tokens array
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


async def fetch_page(session: aiohttp.ClientSession,
                     url: str, offset: int = 0) -> list:
    """Fetch one page of markets."""
    page_url = f"{url}&offset={offset}"
    try:
        async with session.get(
            page_url,
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "Mozilla/5.0"},
        ) as r:
            if r.status != 200:
                return []
            data = await r.json(content_type=None)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("events", "markets", "data", "results"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
    except Exception as e:
        logger.debug(f"Page fetch error {page_url}: {e}")
    return []


async def fetch_polymarket_weather_section() -> dict[str, list[TemperatureBucket]]:
    """
    Fetch temperature markets from Polymarket.
    Tries temperature sub-tag first, falls back to weather tag + client-side filter.
    Paginates until no more results.
    """
    raw_markets = []
    working_url = None

    async with aiohttp.ClientSession() as session:

        # Find first working endpoint
        for base_url in TEMPERATURE_ENDPOINTS:
            items = await fetch_page(session, base_url, offset=0)
            if items:
                working_url = base_url
                raw_markets.extend(items)
                logger.info(f"✅ Endpoint working: {base_url} → {len(items)} items (page 1)")
                break

        if not working_url:
            logger.warning("⚠️ No Polymarket endpoint returned data.")
            return {}

        # Paginate: keep fetching until we get fewer than 100 results
        offset = 100
        while True:
            items = await fetch_page(session, working_url, offset=offset)
            if not items:
                break
            raw_markets.extend(items)
            logger.info(f"📄 Page offset={offset}: {len(items)} items")
            if len(items) < 100:
                break
            offset += 100
            await asyncio.sleep(0.3)  # Be polite to the API

    logger.info(f"📦 Total raw items fetched: {len(raw_markets)}")

    # Flatten events → nested markets, then parse
    city_markets: dict[str, list[TemperatureBucket]] = {}

    for item in raw_markets:
        parent_q = item.get("title") or item.get("question") or ""
        nested   = item.get("markets", [])

        if nested:
            for mkt in nested:
                buckets = parse_market(mkt, parent_question=parent_q)
                for b in buckets:
                    city_markets.setdefault(b.city, []).append(b)
        else:
            buckets = parse_market(item)
            for b in buckets:
                city_markets.setdefault(b.city, []).append(b)

    # Log what we found
    total_buckets = sum(len(v) for v in city_markets.values())
    cities_found  = sorted(city_markets.keys())
    logger.info(f"🌍 Temperature markets found: {total_buckets} buckets across {len(cities_found)} cities")
    logger.info(f"🏙️  Cities: {cities_found}")

    return city_markets
