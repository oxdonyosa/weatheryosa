"""
Bot configuration — all settings in one place.
Secrets come from environment variables (set in Railway dashboard).
"""

import os

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Strategy Thresholds ───────────────────────────────────────────────────────
ENTRY_THRESHOLD      = float(os.environ.get("ENTRY_THRESHOLD", "0.15"))   # 15%
EXIT_THRESHOLD       = float(os.environ.get("EXIT_THRESHOLD",  "0.45"))   # 45%
MAX_POSITION_USD     = float(os.environ.get("MAX_POSITION_USD", "2.00"))
MAX_SIGNALS_PER_SCAN = int(os.environ.get("MAX_SIGNALS_PER_SCAN", "5"))

# ── Scan Settings ─────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS = int(os.environ.get("SCAN_INTERVAL_SECONDS", "120"))  # 2 min

# ── Cities ────────────────────────────────────────────────────────────────────
CITIES = {
    "New York City": {
        "lat": 40.7128, "lon": -74.0060,
        "search_terms": ["New York", "NYC", "Manhattan"],
    },
    "Chicago": {
        "lat": 41.8781, "lon": -87.6298,
        "search_terms": ["Chicago"],
    },
    "Seattle": {
        "lat": 47.6062, "lon": -122.3321,
        "search_terms": ["Seattle"],
    },
    "Atlanta": {
        "lat": 33.7490, "lon": -84.3880,
        "search_terms": ["Atlanta"],
    },
    "Dallas": {
        "lat": 32.7767, "lon": -96.7970,
        "search_terms": ["Dallas"],
    },
    "Miami": {
        "lat": 25.7617, "lon": -80.1918,
        "search_terms": ["Miami"],
    },
}

# ── Polymarket ────────────────────────────────────────────────────────────────
POLYMARKET_GAMMA_API    = "https://gamma-api.polymarket.com"
WEATHER_MARKET_KEYWORDS = ["temperature", "high temp", "low temp", "degrees", "weather"]

# ── NOAA ──────────────────────────────────────────────────────────────────────
NOAA_API_BASE  = "https://api.weather.gov"
NOAA_USER_AGENT = "PolymarketWeatherSignalBot/1.0 (github.com/yourusername/weatherbot)"
