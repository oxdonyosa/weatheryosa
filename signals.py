"""
Signal engine — uses NOAA forecast + Polymarket weather section data.
NOAA tells us which bucket SHOULD resolve YES (ground truth).
We then find where the market price disagrees.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from noaa import NOAAForecast
from polymarket import TemperatureBucket, match_buckets_with_noaa
from config import ENTRY_THRESHOLD, EXIT_THRESHOLD, MAX_POSITION_USD, MAX_SIGNALS_PER_SCAN

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    signal_type:    str          # "BUY" | "AVOID"
    city:           str
    forecast_high:  float
    forecast_low:   Optional[float]
    bucket_outcome: str
    yes_price:      float
    edge:           float
    question:       str
    market_url:     str
    volume_usd:     float
    suggested_size: float
    noaa_desc:      str
    detected_at:    datetime
    confidence:     str

    def to_telegram_message(self) -> str:
        emoji      = "🟢" if self.signal_type == "BUY" else "🔴"
        conf_emoji = {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "💧"}.get(self.confidence, "")
        edge_pct   = f"{self.edge * 100:.1f}%"
        temp_line  = f"High {self.forecast_high:.0f}°F"
        if self.forecast_low:
            temp_line += f" / Low {self.forecast_low:.0f}°F"

        if self.signal_type == "BUY":
            logic = (
                f"NOAA forecast lands in this bucket ✅\n"
                f"Market only prices it at *{self.yes_price:.0%}*\n"
                f"Edge: *{edge_pct}* below {ENTRY_THRESHOLD:.0%} threshold"
            )
        else:
            logic = (
                f"NOAA forecast does NOT land here ❌\n"
                f"Market overprices it at *{self.yes_price:.0%}*\n"
                f"Edge: *{edge_pct}* above {EXIT_THRESHOLD:.0%} threshold"
            )

        return (
            f"{emoji} *{self.signal_type} SIGNAL* {conf_emoji}\n"
            f"\n"
            f"📍 *City:* {self.city}\n"
            f"🌡️ *NOAA Forecast:* {temp_line}\n"
            f"☁️ *Conditions:* {self.noaa_desc}\n"
            f"\n"
            f"📊 *Market:*\n"
            f"_{self.question}_\n"
            f"\n"
            f"🎯 *Bucket:* `{self.bucket_outcome}`\n"
            f"💰 *Market Price:* {self.yes_price:.0%}\n"
            f"📉 *Signal Logic:* {logic}\n"
            f"💵 *Suggested Size:* ${self.suggested_size:.2f}\n"
            f"📦 *Volume:* ${self.volume_usd:,.0f}\n"
            f"\n"
            f"🔗 [Open on Polymarket]({self.market_url})\n"
            f"\n"
            f"⏰ `{self.detected_at.strftime('%Y-%m-%d %H:%M UTC')}`\n"
            f"⚠️ _Signal only — not financial advice. DYOR._"
        )


def confidence(yes_price: float, edge: float, volume: float) -> str:
    score  = 2 if edge >= 0.10 else (1 if edge >= 0.05 else 0)
    score += 2 if volume >= 10_000 else (1 if volume >= 1_000 else 0)
    score += 1 if yes_price <= 0.08 else 0
    return "HIGH" if score >= 4 else ("MEDIUM" if score >= 2 else "LOW")


def generate_signals(forecasts: dict, markets: dict) -> list:
    """
    Core logic:
    1. For each city, tag every bucket with whether NOAA forecast hits it
    2. NOAA hits + market underpriced  → BUY signal
    3. NOAA misses + market overpriced → AVOID signal
    """
    signals = []

    for city, forecast in forecasts.items():
        if forecast.high_f is None:
            continue

        raw_buckets = markets.get(city, [])
        if not raw_buckets:
            continue

        # Tag each bucket: does NOAA forecast land here?
        buckets = match_buckets_with_noaa(raw_buckets, forecast.high_f)

        noaa_matched = [b for b in buckets if b.noaa_match]
        logger.info(
            f"🔎 {city}: NOAA says {forecast.high_f}°F → "
            f"{len(noaa_matched)}/{len(buckets)} buckets match"
        )

        for bucket in buckets:
            if bucket.noaa_match and bucket.yes_price < ENTRY_THRESHOLD:
                # NOAA says YES, market disagrees — underpriced
                edge = ENTRY_THRESHOLD - bucket.yes_price
                signals.append(Signal(
                    signal_type    = "BUY",
                    city           = city,
                    forecast_high  = forecast.high_f,
                    forecast_low   = forecast.low_f,
                    bucket_outcome = bucket.outcome,
                    yes_price      = bucket.yes_price,
                    edge           = edge,
                    question       = bucket.question,
                    market_url     = bucket.market_url,
                    volume_usd     = bucket.volume_usd,
                    suggested_size = MAX_POSITION_USD,
                    noaa_desc      = forecast.description,
                    detected_at    = datetime.utcnow(),
                    confidence     = confidence(bucket.yes_price, edge, bucket.volume_usd),
                ))
                logger.info(f"🟢 BUY  {city} | {bucket.outcome} | {bucket.yes_price:.0%} | NOAA={forecast.high_f}°F ✅ match")

            elif not bucket.noaa_match and bucket.yes_price > EXIT_THRESHOLD:
                # NOAA says NO, market overprices it
                edge = bucket.yes_price - EXIT_THRESHOLD
                signals.append(Signal(
                    signal_type    = "AVOID",
                    city           = city,
                    forecast_high  = forecast.high_f,
                    forecast_low   = forecast.low_f,
                    bucket_outcome = bucket.outcome,
                    yes_price      = bucket.yes_price,
                    edge           = edge,
                    question       = bucket.question,
                    market_url     = bucket.market_url,
                    volume_usd     = bucket.volume_usd,
                    suggested_size = MAX_POSITION_USD,
                    noaa_desc      = forecast.description,
                    detected_at    = datetime.utcnow(),
                    confidence     = confidence(bucket.yes_price, edge, bucket.volume_usd),
                ))
                logger.info(f"🔴 AVOID {city} | {bucket.outcome} | {bucket.yes_price:.0%} | NOAA={forecast.high_f}°F ❌ no match")

    # Best signals first: BUY before AVOID, largest edge first
    signals.sort(key=lambda s: (s.signal_type != "BUY", -s.edge))
    return signals[:MAX_SIGNALS_PER_SCAN]
