"""
Signal engine.
Three signal types:
  🟢 BUY        — Weather says YES, market underprices it (<15%)
  🔴 AVOID      — Weather says NO, market overprices it (>45%)
  💎 CONVICTION — Weather strongly agrees with top bucket regardless of price
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from weather import CityForecast
from polymarket import TemperatureBucket, forecast_hits_bucket
from config import (ENTRY_THRESHOLD, EXIT_THRESHOLD, MAX_POSITION_USD,
                    MAX_SIGNALS_PER_SCAN, CONVICTION_MIN_EDGE, CONVICTION_MIN_VOL)

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    signal_type:    str          # "BUY" | "AVOID" | "CONVICTION"
    city:           str
    forecast_high:  float        # Always in °C for display
    forecast_high_f: float
    forecast_low:   Optional[float]
    forecast_low_f: Optional[float]
    bucket_outcome: str
    yes_price:      float
    edge:           float
    question:       str
    market_url:     str
    volume_usd:     float
    suggested_size: float
    weather_desc:   str
    weather_source: str
    detected_at:    datetime
    confidence:     str

    def to_telegram_message(self) -> str:
        emoji = {"BUY": "🟢", "AVOID": "🔴", "CONVICTION": "💎"}.get(self.signal_type, "⚪")
        conf_emoji = {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "💧"}.get(self.confidence, "")

        temp_line = f"{self.forecast_high:.1f}°C / {self.forecast_high_f:.0f}°F"
        if self.forecast_low is not None:
            temp_line += f"  (Low {self.forecast_low:.1f}°C / {self.forecast_low_f:.0f}°F)"

        if self.signal_type == "BUY":
            logic = (
                f"Forecast lands in this bucket ✅\n"
                f"Market only prices it at *{self.yes_price:.0%}*\n"
                f"Edge: *{self.edge*100:.1f}%* below {ENTRY_THRESHOLD:.0%} threshold"
            )
        elif self.signal_type == "AVOID":
            logic = (
                f"Forecast does NOT land here ❌\n"
                f"Market overprices at *{self.yes_price:.0%}*\n"
                f"Edge: *{self.edge*100:.1f}%* above {EXIT_THRESHOLD:.0%} threshold"
            )
        else:  # CONVICTION
            logic = (
                f"Forecast strongly agrees with this bucket 🎯\n"
                f"Market prices it at *{self.yes_price:.0%}* — looks correct\n"
                f"High conviction lay — weather data confident here"
            )

        return (
            f"{emoji} *{self.signal_type} SIGNAL* {conf_emoji}\n"
            f"\n"
            f"📍 *City:* {self.city}\n"
            f"🌡️ *Forecast:* High {temp_line}\n"
            f"☁️ *Conditions:* {self.weather_desc}\n"
            f"📡 *Source:* {self.weather_source}\n"
            f"\n"
            f"📊 *Market:*\n"
            f"_{self.question}_\n"
            f"\n"
            f"🎯 *Bucket:* `{self.bucket_outcome}`\n"
            f"💰 *Market Price:* {self.yes_price:.0%}\n"
            f"📉 *Signal:* {logic}\n"
            f"💵 *Suggested Size:* ${self.suggested_size:.2f}\n"
            f"📦 *Volume:* ${self.volume_usd:,.0f}\n"
            f"\n"
            f"🔗 [Open on Polymarket]({self.market_url})\n"
            f"\n"
            f"⏰ `{self.detected_at.strftime('%Y-%m-%d %H:%M UTC')}`\n"
            f"⚠️ _Signal only — not financial advice. DYOR._"
        )


def score_confidence(yes_price: float, edge: float, volume: float) -> str:
    score  = 2 if edge >= 0.10 else (1 if edge >= 0.05 else 0)
    score += 2 if volume >= 10_000 else (1 if volume >= 1_000 else 0)
    score += 1 if yes_price <= 0.08 or yes_price >= 0.70 else 0
    return "HIGH" if score >= 4 else ("MEDIUM" if score >= 2 else "LOW")


def generate_signals(forecasts: dict[str, CityForecast],
                     city_markets: dict[str, list[TemperatureBucket]]) -> list[Signal]:
    """
    Core matching logic:
    For every city that has both a forecast AND Polymarket markets:
      1. Tag each bucket: does the forecast temperature land in it?
      2. Generate BUY / AVOID / CONVICTION signals
    """
    signals = []

    for city, buckets in city_markets.items():
        # Try to find forecast — match on city name (case-insensitive, partial ok)
        forecast = None
        for fname, f in forecasts.items():
            if city.lower() in fname.lower() or fname.lower() in city.lower():
                forecast = f
                break

        if not forecast:
            logger.debug(f"No forecast found for Polymarket city: {city}")
            continue

        high_c = forecast.high_c
        high_f = forecast.high_f
        low_c  = forecast.low_c
        low_f  = forecast.low_f

        # Tag each bucket with NOAA/Open-Meteo match
        matched = []
        for b in buckets:
            b.noaa_match = forecast_hits_bucket(
                high_c, high_f,
                b.low_bound, b.high_bound,
                b.is_above, b.is_below,
                b.is_celsius,
            )
            if b.noaa_match:
                matched.append(b)

        logger.info(
            f"🔎 {city}: forecast {high_c:.1f}°C/{high_f:.0f}°F → "
            f"{len(matched)}/{len(buckets)} buckets match"
        )

        for b in buckets:
            now = datetime.utcnow()
            base = dict(
                city=city,
                forecast_high=high_c, forecast_high_f=high_f,
                forecast_low=low_c, forecast_low_f=low_f,
                bucket_outcome=b.outcome,
                yes_price=b.yes_price,
                question=b.question,
                market_url=b.market_url,
                volume_usd=b.volume_usd,
                suggested_size=MAX_POSITION_USD,
                weather_desc=forecast.description,
                weather_source=forecast.source,
                detected_at=now,
            )

            if b.noaa_match and b.yes_price < ENTRY_THRESHOLD:
                # ── BUY: forecast says YES, market underprices ────────────────
                edge = ENTRY_THRESHOLD - b.yes_price
                signals.append(Signal(
                    signal_type="BUY", edge=edge,
                    confidence=score_confidence(b.yes_price, edge, b.volume_usd),
                    **base,
                ))
                logger.info(f"🟢 BUY  {city} | {b.outcome} | {b.yes_price:.0%} | ✅ match")

            elif not b.noaa_match and b.yes_price > EXIT_THRESHOLD:
                # ── AVOID: forecast says NO, market overprices ────────────────
                edge = b.yes_price - EXIT_THRESHOLD
                signals.append(Signal(
                    signal_type="AVOID", edge=edge,
                    confidence=score_confidence(b.yes_price, edge, b.volume_usd),
                    **base,
                ))
                logger.info(f"🔴 AVOID {city} | {b.outcome} | {b.yes_price:.0%} | ❌ no match")

            elif (b.noaa_match
                  and b.volume_usd >= CONVICTION_MIN_VOL
                  and b.yes_price >= 0.25):
                # ── CONVICTION: forecast agrees, price looks right,
                #    but high confidence in the call → worth flagging ──────────
                # Edge here = how much higher the price is vs the next bucket
                # (proxy for market conviction alignment)
                other_prices = [x.yes_price for x in buckets
                                if not x.noaa_match and x.yes_price > 0.05]
                edge = b.yes_price - (max(other_prices) if other_prices else 0)
                if edge >= CONVICTION_MIN_EDGE:
                    signals.append(Signal(
                        signal_type="CONVICTION", edge=edge,
                        confidence=score_confidence(b.yes_price, edge, b.volume_usd),
                        **base,
                    ))
                    logger.info(f"💎 CONVICTION {city} | {b.outcome} | {b.yes_price:.0%} | strong agreement")

    # Sort: BUY first, then CONVICTION, then AVOID — each group by edge desc
    order = {"BUY": 0, "CONVICTION": 1, "AVOID": 2}
    signals.sort(key=lambda s: (order.get(s.signal_type, 9), -s.edge))
    return signals[:MAX_SIGNALS_PER_SCAN]
