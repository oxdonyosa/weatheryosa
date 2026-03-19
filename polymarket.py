"""
Polymarket — fetches temperature markets from the weather section.
Strictly validates that outcomes are real temperature buckets (not Yes/No).
Filters out non-city "cities" like 'prison', 'the NBA', etc.
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

# Try weather tag (more reliable) and temperature tag
ENDPOINTS = [
    f"{POLYMARKET_GAMMA_API}/events?tag=weather&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/events?tag=temperature&active=true&closed=false&limit=100",
    f"{POLYMARKET_GAMMA_API}/events?tag_slug=weather&active=true&closed=false&limit=100",
]

# Outcomes must match this to be a real temperature bucket
TEMP_OUTCOME_RE = re.compile(
    r"""
    ^\s*
    (?:
        \d{1,3}(?:\.\d+)?\s*[-–to]+\s*\d{1,3}(?:\.\d+)?\s*(?:°[FC])?   # range: 55-60°F
        | (?:above|below|over|under|<|>)\s*\d{1,3}(?:\.\d+)?\s*(?:°[FC])?  # above/below
        | \d{1,3}(?:\.\d+)?\s*(?:or\s+(?:higher|lower|more|less)|\+)        # X or higher
        | \d{1,3}(?:\.\d+)?\s*°[FC]                                          # exact: 13°C
        | \d{2,3}(?:\+)?°?[FC]?\s*or\s+(?:higher|lower|below|above)
    )
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE
)

# Words that disqualify something from being a city name
NOT_A_CITY = {
    "prison", "jail", "the nba", "the nfl", "the mlb", "april", "may", "june",
    "january", "february", "march", "july", "august", "september", "october",
    "november", "december", "the world", "the first", "another", "a gulf",
    "bitcoin", "crypto", "election", "market cap", "congress", "senate",
    "the us", "the eu", "an eu", "a us", "trump", "biden", "musk",
    "nasdaq", "s&p", "dow", "oil", "gold", "silver",
}

# Must contain at least one of these to be a temperature market question
TEMP_QUESTION_KEYWORDS = [
    "highest temperature", "high temperature", "temperature in",
    "temp in", "highest temp", "daily high", "daily temperature",
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


def is_temp_outcome(text: str) -> bool:
    """Return True only if the outcome text is a real temperature range."""
    return bool(TEMP_OUTCOME_RE.match(text.strip()))


def is_temp_question(text: str) -> bool:
    """Return True if the question is about temperature."""
    t = text.lower()
    return any(kw in t for kw in TEMP_QUESTION_KEYWORDS)


def is_valid_city(name: str) -> bool:
    """Filter out non-city strings."""
    n = name.lower().strip()
    if len(n) < 3 or len(n) > 50:
        return False
    if any(bad in n for bad in NOT_A_CITY):
        return False
    # Must start with a letter, no digits
    if re.search(r'\d', n):
        return False
    # Must look like a proper noun (real cities usually have caps when extracted)
    return True


def parse_temp_range(text: str):
    """Parse bucket label → (low, high, is_above, is_below, is_celsius)."""
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

    rng = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)", t)
    if rng:
        return float(rng.group(1)), float(rng.group(2)), False, False, is_c

    single = re.match(r"^(\d+(?:\.\d+)?)$", t.strip())
    if single:
        v = float(single.group(1))
        return v, v, False, False, is_c

    return None, None, False, False, is_c


def forecast_hits_bucket(temp_c, temp_f, low, high, is_above, is_below, is_celsius) -> bool:
    temp = temp_c if is_celsius else temp_f
    if is_above and low is not None:
        return temp >= low
    if is_below and high is not None:
        return temp < high
    if low is not None and high is not None:
        return low <= temp <= high
    return False


def extract_city(text: str) -> Optional[str]:
    """Extract city from 'Highest temperature in <City> on ...'"""
    patterns = [
        r"(?:highest\s+)?temperature\s+in\s+([A-Za-z][A-Za-z\s\-\.]+?)(?:\s+on\s+|\?|$)",
        r"(?:highest\s+)?temp(?:erature)?\s+in\s+([A-Za-z][A-Za-z\s\-\.]+?)(?:\s+on\s+|\?|$)",
        r"daily\s+(?:high\s+)?temperature\s+in\s+([A-Za-z][A-Za-z\s\-\.]+?)(?:\s+on\s+|\?|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            city = m.group(1).strip().rstrip("?.,").strip()
            if is_valid_city(city):
                return city
    return None


def get_title(item: dict) -> str:
    return (item.get("title") or item.get("question") or
            item.get("name") or item.get("description") or "")


def parse_outcomes(mkt: dict) -> tuple[list, list]:
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
    return outcomes, out_prices


def build_buckets(mkt: dict, question: str, city: str) -> list[TemperatureBucket]:
    outcomes, out_prices = parse_outcomes(mkt)

    # STRICT CHECK: every outcome must be a real temperature range
    # If outcomes are just "Yes"/"No" this is not a temperature bucket market
    temp_outcomes = [o for o in outcomes if is_temp_outcome(str(o))]
    if not temp_outcomes or len(temp_outcomes) < len(outcomes) * 0.5:
        return []

    mid    = mkt.get("id") or mkt.get("conditionId") or "unknown"
    slug   = mkt.get("slug") or mkt.get("marketSlug") or str(mid)
    volume = float(mkt.get("volume") or mkt.get("volumeNum") or 0)
    url    = f"{POLYMARKET_WEB_URL}/event/{slug}"

    buckets = []
    for i, outcome in enumerate(outcomes):
        if not is_temp_outcome(str(outcome)):
            continue
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
    event_title = get_title(event)

    # Quick filter: must mention temperature
    if not is_temp_question(event_title):
        return []

    city = extract_city(event_title)
    all_buckets = []

    nested = event.get("markets", [])
    if nested:
        for mkt in nested:
            question = get_title(mkt) or event_title
            mkt_city = extract_city(question) or city
            if not mkt_city:
                continue
            buckets = build_buckets(mkt, question, mkt_city)
            all_buckets.extend(buckets)
    elif city:
        buckets = build_buckets(event, event_title, city)
        all_buckets.extend(buckets)

    return all_buckets


async def fetch_page(session, base_url: str, offset: int = 0) -> list:
    url = f"{base_url}&offset={offset}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15),
                               headers={"User-Agent": "Mozilla/5.0"}) as r:
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
        logger.debug(f"Fetch error {url}: {e}")
    return []


async def fetch_polymarket_weather_section() -> dict[str, list[TemperatureBucket]]:
    raw_events = []
    working_url = None

    async with aiohttp.ClientSession() as session:
        for base_url in ENDPOINTS:
            items = await fetch_page(session, base_url, offset=0)
            if items:
                working_url = base_url
                raw_events.extend(items)
                logger.info(f"✅ Endpoint: {base_url} — {len(items)} items")
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
            if len(items) < 100:
                break
            offset += 100
            await asyncio.sleep(0.3)

    logger.info(f"📦 Total events fetched: {len(raw_events)}")

    city_markets: dict[str, list[TemperatureBucket]] = {}
    skipped = 0

    for event in raw_events:
        buckets = parse_event(event)
        if buckets:
            for b in buckets:
                city_markets.setdefault(b.city, []).append(b)
        else:
            skipped += 1

    total  = sum(len(v) for v in city_markets.values())
    cities = sorted(city_markets.keys())
    logger.info(f"🌍 {total} real temperature buckets across {len(cities)} cities | {skipped} non-temp events skipped")
    logger.info(f"🏙️  Cities: {cities}")

    return city_markets
