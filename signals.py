"""
Signal generation — compares NOAA forecasts vs Polymarket prices.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from noaa import NOAAForecast
from polymarket import TemperatureBucket, forecast_hits_bucket
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
    confidence:     str          # "HIGH" | "MEDIUM" | "LOW"

    def to_telegram_message(self) -> str:
        emoji      = "🟢" if self.signal_type == "BUY" else "🔴"
        conf_emoji = {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "💧"}.get(self.confidence, "")
        edge_pct   = f"{self.edge * 100:.1f}%"
        temp_line  = f"High {self.forecast_high:.0f}°F"
        if self.forecast_low:
            temp_line += f" / Low {self.forecast_low:.0f}°F"

        if self.signal_type == "BUY":
            reason = (f"NOAA says this bucket resolves ✅ YES\n"
                      f"but market only prices it at {self.yes_price:.0%}\n"
                      f"Edge: {edge_pct} below {ENTRY_THRESHOLD:.0%} entry threshold")
        else:
            reason = (f"NOAA says this bucket resolves ❌ NO\n"
                      f"but market prices it at {self.yes_price:.0%}\n"
                      f"Edge: {edge_pct} above {EXIT_THRESHOLD:.0%} exit threshold")

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
            f"💰 *Price:* {self.yes_price:.0%}\n"
            f"📉 *Why:* {reason}\n"
            f"💵 *Suggested Size:* ${self.suggested_size:.2f}\n"
            f"📦 *Volume:* ${self.volume_usd:,.0f}\n"
            f"\n"
            f"🔗 [Open on Polymarket]({self.market_url})\n"
            f"\n"
            f"⏰ `{self.detected_at.strftime('%Y-%m-%d %H:%M UTC')}`\n"
            f"⚠️ _Signal only — not financial advice. DYOR._"
        )


def confidence(yes_price, edge, volume) -> str:
    score  = 2 if edge >= 0.10 else (1 if edge >= 0.05 else 0)
    score += 2 if volume >= 10_000 else (1 if volume >= 1_000 else 0)
    score += 1 if yes_price <= 0.08 else 0
    return "HIGH" if score >= 4 else ("MEDIUM" if score >= 2 else "LOW")


def generate_signals(forecasts: dict, markets: dict) -> list:
    signals = []

    for city, forecast in forecasts.items():
        if forecast.high_f is None:
            continue
        for bucket in markets.get(city, []):
            hits = forecast_hits_bucket(
                forecast.high_f,
                bucket.low_bound, bucket.high_bound,
                bucket.is_above, bucket.is_below,
            )

            if hits and bucket.yes_price < ENTRY_THRESHOLD:
                edge = ENTRY_THRESHOLD - bucket.yes_price
                signals.append(Signal(
                    signal_type="BUY", city=city,
                    forecast_high=forecast.high_f, forecast_low=forecast.low_f,
                    bucket_outcome=bucket.outcome, yes_price=bucket.yes_price,
                    edge=edge, question=bucket.question, market_url=bucket.market_url,
                    volume_usd=bucket.volume_usd, suggested_size=MAX_POSITION_USD,
                    noaa_desc=forecast.description, detected_at=datetime.utcnow(),
                    confidence=confidence(bucket.yes_price, edge, bucket.volume_usd),
                ))
                logger.info(f"🟢 BUY  {city} | {bucket.outcome} | {bucket.yes_price:.0%} | NOAA {forecast.high_f}°F")

            elif not hits and bucket.yes_price > EXIT_THRESHOLD:
                edge = bucket.yes_price - EXIT_THRESHOLD
                signals.append(Signal(
                    signal_type="AVOID", city=city,
                    forecast_high=forecast.high_f, forecast_low=forecast.low_f,
                    bucket_outcome=bucket.outcome, yes_price=bucket.yes_price,
                    edge=edge, question=bucket.question, market_url=bucket.market_url,
                    volume_usd=bucket.volume_usd, suggested_size=MAX_POSITION_USD,
                    noaa_desc=forecast.description, detected_at=datetime.utcnow(),
                    confidence=confidence(bucket.yes_price, edge, bucket.volume_usd),
                ))
                logger.info(f"🔴 AVOID {city} | {bucket.outcome} | {bucket.yes_price:.0%} (overpriced) | NOAA {forecast.high_f}°F")

    signals.sort(key=lambda s: (s.signal_type != "BUY", -s.edge))
    return signals[:MAX_SIGNALS_PER_SCAN]
