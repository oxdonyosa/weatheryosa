# 🌦️ Polymarket Weather Signal Bot

Scans **NOAA forecast data** vs **Polymarket temperature market prices** every 2 minutes.
Sends **Telegram alerts** when the market is mispriced. **No auto-trading — signals only.**

---

## How It Works

```
Every 2 minutes:
  1. Fetch NOAA high/low temp forecasts for 6 cities (free, no API key)
  2. Scan all active Polymarket temperature bucket markets
  3. Compare: does NOAA agree with what the market is pricing?
  4. NOAA says YES, market < 15%  →  🟢 BUY signal
  5. NOAA says NO,  market > 45%  →  🔴 AVOID signal
  6. Send alert to your Telegram
```

---

