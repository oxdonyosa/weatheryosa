"""
Polymarket — fetches temperature markets, parses event titles dynamically.
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

TEMPERATURE_ENDPOINTS = [
    f"{POLYMARKET_GAMMA_API}/events?tag=temperature&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/events?tag_slug=temperature&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/markets?tag=temperature&active=true&closed=false&limit=100",
]


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
        bool(re.search(r"\b\d{1,2}\b", text)) and
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


def extract_city(text: str) -> Optional[str]:
    """Extract city name from Polymarket event/market title."""
    patterns = [
        r"(?:highest\s+)?temperature\s+in\s+([A-Za-z][A-Za-z\s\-]+?)(?:\s+on\s+|\?|$)",
        r"(?:highest\s+)?temp(?:erature)?\s+in\s+([A-Za-z][A-Za-z\s\-]+?)(?:\s+on\s+|\?|$)",
        r"\bin\s+([A-Z][a-zA-Z\s\-]+?)(?:\s+on\s+|\?|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            city = m.group(1).strip().rstrip("?.,").strip()
            # Sanity check — real city names are 2-40 chars
            if 2 < len(city) < 40:
                return city
    return None


def get_title(item: dict) -> str:
    """Get the best available title/question from an item."""
    return (item.get("title") or
            item.get("question") or
            item.get("name") or
            item.get("description") or "")


def parse_outcomes(mkt: dict) -> tuple[list, list]:
    """Extract outcomes and prices from a market dict."""
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

    return outcomes, out_prices


def build_buckets(mkt: dict, question: str, city: str) -> list[TemperatureBucket]:
    """Build TemperatureBucket list from a market dict."""
    mid    = mkt.get("id") or mkt.get("conditionId") or "unknown"
    slug   = mkt.get("slug") or mkt.get("marketSlug") or str(mid)
    volume = float(mkt.get("volume") or mkt.get("volumeNum") or 0)
    url    = f"{POLYMARKET_WEB_URL}/event/{slug}"

    outcomes, out_prices = parse_outcomes(mkt)

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


def parse_event(event: dict) -> list[TemperatureBucket]:
    """
    Parse a Polymarket event (which may contain nested markets).
    The event title is the question e.g. 'Highest temperature in Atlanta on March 20?'
    """
    event_title = get_title(event)
    city        = extract_city(event_title)

    all_buckets = []

    # Case 1: Event has nested markets — each market is a bucket group
    nested_markets = event.get("markets", [])
    if nested_markets:
        for mkt in nested_markets:
            # Use event title as question since nested markets often lack one
            question = get_title(mkt) or event_title
            mkt_city = extract_city(question) or city
            if not mkt_city:
                continue
            buckets = build_buckets(mkt, question, mkt_city)
            all_buckets.extend(buckets)
        return all_buckets

    # Case 2: Event itself is a market (flat structure)
    if city:
        buckets = build_buckets(event, event_title, city)
        all_buckets.extend(buckets)

    return all_buckets


async def fetch_page(session: aiohttp.ClientSession,
                     base_url: str, offset: int = 0) -> list:
    url = f"{base_url}&offset={offset}"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "Mozilla/5.0"},
        ) as r:
            if r.status != 200:
                logger.debug(f"❌ {r.status} — {url}")
                return []
            data = await r.json(content_type=None)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("events", "markets", "data", "results"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
    except Exception as e:
        logger.debug(f"Fetch error {url}: {e}")
    return []


async def fetch_polymarket_weather_section() -> dict[str, list[TemperatureBucket]]:
    raw_events = []
    working_url = None

    async with aiohttp.ClientSession() as session:
        # Find working endpoint
        for base_url in TEMPERATURE_ENDPOINTS:
            items = await fetch_page(session, base_url, offset=0)
            if items:
                working_url = base_url
                raw_events.extend(items)
                logger.info(f"✅ Endpoint working: {base_url} — {len(items)} items")

                # Log first item structure to debug
                if items:
                    sample = items[0]
                    logger.info(f"📋 Sample item keys: {list(sample.keys())}")
                    logger.info(f"📋 Sample title: {get_title(sample)}")
                    nested = sample.get("markets", [])
                    if nested:
                        logger.info(f"📋 Nested markets: {len(nested)}, first keys: {list(nested[0].keys())}")
                        logger.info(f"📋 First nested title: {get_title(nested[0])}")
                break

        if not working_url:
            logger.warning("⚠️ No endpoint returned data.")
            return {}

        # Paginate
        offset = 100
        while len(raw_events) < 500:
            items = await fetch_page(session, working_url, offset=offset)
            if not items:
                break
            raw_events.extend(items)
            logger.info(f"📄 offset={offset}: {len(items)} more items")
            if len(items) < 100:
                break
            offset += 100
            await asyncio.sleep(0.3)

    logger.info(f"📦 Total events fetched: {len(raw_events)}")

    # Parse all events into city buckets
    city_markets: dict[str, list[TemperatureBucket]] = {}
    skipped = 0

    for event in raw_events:
        buckets = parse_event(event)
        if buckets:
            for b in buckets:
                city_markets.setdefault(b.city, []).append(b)
        else:
            skipped += 1

    total = sum(len(v) for v in city_markets.values())
    cities = sorted(city_markets.keys())
    logger.info(f"🌍 Found {total} buckets across {len(cities)} cities | {skipped} events skipped")
    logger.info(f"🏙️  Cities: {cities}")

    return city_markets
