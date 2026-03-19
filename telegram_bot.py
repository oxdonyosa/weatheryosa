"""
Telegram bot — commands and signal delivery.
"""

import asyncio
import logging
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from config import (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                    ENTRY_THRESHOLD, EXIT_THRESHOLD, SCAN_INTERVAL_SECONDS)

logger = logging.getLogger(__name__)

bot_state = {
    "last_scan":     None,
    "total_signals": 0,
    "last_signals":  [],
    "scan_count":    0,
    "active_cities": [],
}

_app: Application = None


async def send_signal_message(text: str):
    if not _app or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured.")
        return
    try:
        await _app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, text=text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
        )
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


async def reply(update: Update, text: str):
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
    )


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await reply(update,
        "👋 *Polymarket Weather Signal Bot*\n\n"
        "I pull live markets from the *Polymarket weather section*, cross-reference "
        "every bucket with NOAA (US) or Open-Meteo (global) forecasts, "
        "and alert you when the market is mispriced — or when there's a strong conviction play.\n\n"
        "*Signal Types:*\n"
        "🟢 *BUY* — Forecast says YES, market < 15%\n"
        "🔴 *AVOID* — Forecast says NO, market > 45%\n"
        "💎 *CONVICTION* — Forecast strongly agrees with top bucket\n\n"
        "*Commands:*\n"
        "/status — Bot status & last scan\n"
        "/cities — Cities active on Polymarket right now\n"
        "/config — Strategy settings\n"
        "/lastsignals — Signals from last scan\n"
        "/help — This message\n\n"
        "⚠️ _Signals only — not financial advice._"
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    last = bot_state["last_scan"]
    last_str = last.strftime("%Y-%m-%d %H:%M UTC") if last else "Not yet run"
    await reply(update,
        f"🤖 *Bot Status*\n\n"
        f"🟢 Running\n"
        f"⏰ Last scan: `{last_str}`\n"
        f"🔢 Scans completed: `{bot_state['scan_count']}`\n"
        f"📊 Total signals sent: `{bot_state['total_signals']}`\n"
        f"⚡ Scan every: `{SCAN_INTERVAL_SECONDS // 60} minutes`"
    )


async def cmd_cities(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cities = bot_state.get("active_cities", [])
    if not cities:
        await reply(update, "😴 No scan run yet — cities will appear after first scan.")
        return
    city_list = "\n".join(f"  • {c}" for c in sorted(cities))
    await reply(update,
        f"🌍 *Cities Active on Polymarket* ({len(cities)})\n\n{city_list}\n\n"
        f"_Updates every scan. Cities come directly from Polymarket's weather section._"
    )


async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await reply(update,
        f"⚙️ *Strategy Configuration*\n\n"
        f"📥 Entry threshold: `{ENTRY_THRESHOLD * 100:.0f}%`\n"
        f"📤 Exit threshold: `{EXIT_THRESHOLD * 100:.0f}%`\n"
        f"🔁 Scan interval: every `{SCAN_INTERVAL_SECONDS // 60}` minutes\n\n"
        f"*Signal Logic:*\n"
        f"🟢 BUY → forecast in bucket + price < {ENTRY_THRESHOLD:.0%}\n"
        f"🔴 AVOID → forecast not in bucket + price > {EXIT_THRESHOLD:.0%}\n"
        f"💎 CONVICTION → forecast matches top bucket with strong edge\n\n"
        f"*Weather Sources:*\n"
        f"🇺🇸 US cities → NOAA weather.gov\n"
        f"🌍 Global cities → Open-Meteo\n\n"
        f"_Edit Railway Variables tab to change thresholds._"
    )


async def cmd_lastsignals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    signals = bot_state["last_signals"]
    if not signals:
        await reply(update, "😴 No signals from the last scan.")
        return
    await reply(update, f"📋 *Last scan — {len(signals)} signal(s):*")
    for sig in signals[:5]:
        await send_signal_message(sig.to_telegram_message())


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def run_telegram_bot():
    global _app
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set.")
        return

    _app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    for cmd, fn in [
        ("start",       cmd_start),
        ("status",      cmd_status),
        ("cities",      cmd_cities),
        ("config",      cmd_config),
        ("lastsignals", cmd_lastsignals),
        ("help",        cmd_help),
    ]:
        _app.add_handler(CommandHandler(cmd, fn))

    await _app.bot.set_my_commands([
        BotCommand("start",       "Welcome & intro"),
        BotCommand("status",      "Bot status & last scan"),
        BotCommand("cities",      "Active cities on Polymarket"),
        BotCommand("config",      "Strategy settings"),
        BotCommand("lastsignals", "Signals from last scan"),
        BotCommand("help",        "Help menu"),
    ])

    logger.info("🤖 Telegram bot running...")
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling(drop_pending_updates=True)

    while True:
        await asyncio.sleep(3600)
