"""
Scan scheduler — runs every 2 minutes.
Dynamic flow: fetch Polymarket weather cities first, then get forecasts for those cities.
"""

import asyncio
import logging
from datetime import datetime
from config import SCAN_INTERVAL_SECONDS
from weather import fetch_forecasts_for_cities
from polymarket import fetch_polymarket_weather_section
from signals import generate_signals
from telegram_bot import send_signal_message, bot_state

logger = logging.getLogger(__name__)

_sent: dict[str, datetime] = {}
COOLDOWN_MINUTES = 10


def _key(sig) -> str:
    return f"{sig.city}|{sig.bucket_outcome}|{sig.signal_type}"

def _already_sent(sig) -> bool:
    k = _key(sig)
    if k in _sent:
        mins = (datetime.utcnow() - _sent[k]).total_seconds() / 60
        return mins < COOLDOWN_MINUTES
    return False

def _mark_sent(sig):
    _sent[_key(sig)] = datetime.utcnow()


async def run_scan():
    logger.info(f"🔍 Scan #{bot_state['scan_count'] + 1} starting...")
    try:
        # 1. Fetch ALL cities from Polymarket weather section (dynamic)
        city_markets = await fetch_polymarket_weather_section()

        if not city_markets:
            logger.warning("No Polymarket weather markets found — skipping scan.")
            return

        active_cities = list(city_markets.keys())
        logger.info(f"🌍 Active cities this scan: {active_cities}")

        # 2. Fetch weather forecasts for exactly those cities
        forecasts = await fetch_forecasts_for_cities(active_cities)

        # 3. Generate signals
        signals = generate_signals(forecasts, city_markets)

        # 4. Update state
        bot_state["last_scan"]      = datetime.utcnow()
        bot_state["scan_count"]    += 1
        bot_state["last_signals"]   = signals
        bot_state["active_cities"]  = active_cities

        # 5. Send new signals
        new = [s for s in signals if not _already_sent(s)]

        if not new:
            logger.info(f"✅ Scan complete — no new signals. ({len(signals)} total found, all already sent)")
            return

        logger.info(f"📣 Sending {len(new)} new signal(s)...")

        if len(new) > 1:
            await send_signal_message(
                f"📡 *{len(new)} Signal(s) Detected*\n"
                f"`{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}`"
            )

        for sig in new:
            await send_signal_message(sig.to_telegram_message())
            _mark_sent(sig)
            bot_state["total_signals"] += 1
            await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        await send_signal_message(f"⚠️ Scan error: `{str(e)[:200]}`")


async def start_scheduler():
    await asyncio.sleep(5)
    logger.info(f"⏱️  Scheduler started — every {SCAN_INTERVAL_SECONDS}s")
    while True:
        await run_scan()
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)
