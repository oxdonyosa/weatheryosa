"""
Polymarket Weather Signal Bot — entry point.
"""

import asyncio
import logging
from scheduler import start_scheduler
from telegram_bot import run_telegram_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("🚀 Polymarket Weather Signal Bot starting...")
    logger.info("🌍 Cities: dynamic — pulled from Polymarket weather section each scan")
    logger.info("📡 Weather: NOAA (US) + Open-Meteo (global)")
    logger.info("⚡ Signals: 🟢 BUY | 🔴 AVOID | 💎 CONVICTION")
    logger.info(f"🔁 Scan interval: every 2 minutes")

    await asyncio.gather(
        start_scheduler(),
        run_telegram_bot(),
    )


if __name__ == "__main__":
    asyncio.run(main())
