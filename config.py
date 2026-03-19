"""
Bot configuration — all settings via Railway environment variables.
No hardcoded cities — cities come dynamically from Polymarket's weather section.
"""

import os

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Signal Thresholds ─────────────────────────────────────────────────────────
ENTRY_THRESHOLD      = float(os.environ.get("ENTRY_THRESHOLD", "0.15"))   # BUY if below 15%
EXIT_THRESHOLD       = float(os.environ.get("EXIT_THRESHOLD",  "0.45"))   # AVOID if above 45%
MAX_POSITION_USD     = float(os.environ.get("MAX_POSITION_USD", "2.00"))
MAX_SIGNALS_PER_SCAN = int(os.environ.get("MAX_SIGNALS_PER_SCAN", "5"))

# ── Conviction Signal ─────────────────────────────────────────────────────────
# Even if not "mispriced", signal when NOAA strongly agrees with top bucket
CONVICTION_MIN_EDGE  = float(os.environ.get("CONVICTION_MIN_EDGE", "0.10"))  # NOAA must be >10% closer than market implies
CONVICTION_MIN_VOL   = float(os.environ.get("CONVICTION_MIN_VOL", "5000"))   # Min $5k volume to care

# ── Scan Settings ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS = int(os.environ.get("SCAN_INTERVAL_SECONDS", "120"))

# ── Weather APIs ──────────────────────────────────────────────────────────────
NOAA_API_BASE       = "https://api.weather.gov"
NOAA_USER_AGENT     = "PolymarketWeatherSignalBot/1.0 (github.com/yourusername/weatherbot)"
OPEN_METEO_API      = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEO_API  = "https://geocoding-api.open-meteo.com/v1/search"

# ── US Cities (use NOAA) ──────────────────────────────────────────────────────
# Any city name containing these strings routes to NOAA
US_CITY_KEYWORDS = [
    "new york", "nyc", "chicago", "seattle", "atlanta",
    "dallas", "miami", "los angeles", "houston", "phoenix",
    "philadelphia", "san antonio", "san diego", "boston",
    "denver", "nashville", "portland", "las vegas",
]

# ── Polymarket ────────────────────────────────────────────────────────────────
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"
POLYMARKET_WEB_URL   = "https://polymarket.com"
