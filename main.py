"""
Polymarket Weather Signal Bot
Scans NOAA forecast data vs Polymarket weather market prices
and sends Telegram signals when mispricing is detected.
NO AUTO-TRADING — signals only.
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
    logger.info("📡 Monitoring: NYC, Chicago, Seattle, Atlanta, Dallas, Miami")
    logger.info("⚡ Scan interval: every 2 minutes")
    logger.info("📊 Entry threshold: 15% | Exit threshold: 45%")

    await asyncio.gather(
        start_scheduler(),
        run_telegram_bot(),
    )


if __name__ == "__main__":
    asyncio.run(main())
