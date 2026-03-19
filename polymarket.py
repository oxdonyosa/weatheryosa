"""
Polymarket Gamma API — scans active weather/temperature markets.
"""

import asyncio
import json
import logging
import re
import aiohttp
from dataclasses import dataclass
from typing import Optional
from config import POLYMARKET_GAMMA_API, WEATHER_MARKET_KEYWORDS

logger = logging.getLogger(__name__)


@dataclass
class TemperatureBucket:
    market_id:   str
    question:    str
    outcome:     str
    yes_price:   float        # 0.0 – 1.0
    no_price:    float
    volume_usd:  float
    low_bound:   Optional[float]
    high_bound:  Optional[float]
    is_above:    bool
    is_below:    bool
    market_url:  str


def parse_temp_range(text: str):
    """Parse bucket label → (low, high, is_above, is_below)."""
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


def forecast_hits_bucket(temp, low, high, is_above, is_below) -> bool:
    if is_above and low is not None:
        return temp >= low
    if is_below and high is not None:
        return temp < high
    if low is not None and high is not None:
        return low <= temp < high
    return False


async def fetch_weather_markets(session, city_name, search_terms) -> list:
    buckets, seen = [], set()

    for term in search_terms:
        params = {"q": f"temperature {term}", "active": "true", "closed": "false", "limit": 50}
        try:
            async with session.get(f"{POLYMARKET_GAMMA_API}/markets", params=params,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    continue
                markets = await r.json()
                if not isinstance(markets, list):
                    markets = markets.get("markets", [])

                for mkt in markets:
                    mid = mkt.get("id") or mkt.get("conditionId", "")
                    if mid in seen:
                        continue
                    q = mkt.get("question", "").lower()
                    if not any(kw in q for kw in WEATHER_MARKET_KEYWORDS):
                        continue
                    if not any(t.lower() in q for t in search_terms):
                        continue

                    seen.add(mid)
                    slug       = mkt.get("slug", mid)
                    market_url = f"https://polymarket.com/event/{slug}"
                    volume     = float(mkt.get("volume", 0) or 0)

                    outcomes   = mkt.get("outcomes", [])
                    out_prices = mkt.get("outcomePrices", [])
                    if isinstance(outcomes, str):
                        try: outcomes = json.loads(outcomes)
                        except: outcomes = []
                    if isinstance(out_prices, str):
                        try: out_prices = json.loads(out_prices)
                        except: out_prices = []

                    for i, outcome in enumerate(outcomes):
                        yes_price = float(out_prices[i]) if i < len(out_prices) else 0.5
                        low, high, is_above, is_below = parse_temp_range(str(outcome))
                        buckets.append(TemperatureBucket(
                            market_id  = f"{mid}_{i}",
                            question   = mkt.get("question", ""),
                            outcome    = str(outcome),
                            yes_price  = yes_price,
                            no_price   = 1.0 - yes_price,
                            volume_usd = volume,
                            low_bound  = low,
                            high_bound = high,
                            is_above   = is_above,
                            is_below   = is_below,
                            market_url = market_url,
                        ))
        except Exception as e:
            logger.error(f"Polymarket fetch failed for {city_name} ({term}): {e}")

    logger.info(f"📈 Polymarket: {len(buckets)} buckets for {city_name}")
    return buckets


async def fetch_all_city_markets(cities: dict) -> dict:
    results = {}
    async with aiohttp.ClientSession() as session:
        tasks = {
            city: fetch_weather_markets(session, city, info["search_terms"])
            for city, info in cities.items()
        }
        lists = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for city, mlist in zip(tasks.keys(), lists):
            results[city] = mlist if isinstance(mlist, list) else []
    return results
