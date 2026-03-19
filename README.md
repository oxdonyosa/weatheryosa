# 🌦️ Polymarket Weather Signal Bot

Pulls **live markets from Polymarket's weather section**, cross-references every temperature bucket against real forecast data, and sends **Telegram alerts** for mispricings and high-conviction plays.

**No auto-trading. Signals only.**

---

## Signal Types

| Signal | Meaning |
|---|---|
| 🟢 **BUY** | Forecast lands in this bucket, market prices it below 15% |
| 🔴 **AVOID** | Forecast does NOT land here, market overprices it above 45% |
| 💎 **CONVICTION** | Forecast strongly agrees with top bucket — high confidence lay even if not "mispriced" |

---

## How It Works

```
Every 2 minutes:
  1. Fetch ALL active markets from Polymarket's weather section
  2. Extract cities dynamically from market titles (no hardcoding)
  3. Fetch forecasts for exactly those cities:
       → US cities  (NYC, Chicago, etc.) → NOAA weather.gov
       → Global cities (London, Tokyo, etc.) → Open-Meteo
  4. For each city, tag every temperature bucket:
       Does the forecast temperature land in this bucket? YES / NO
  5. Generate signals:
       NOAA/Open-Meteo says YES + market < 15%  →  🟢 BUY
       NOAA/Open-Meteo says NO  + market > 45%  →  🔴 AVOID
       Strong forecast agreement + high volume   →  💎 CONVICTION
  6. Send alerts to Telegram
```

---

## File Structure

```
weatherbot/
├── main.py          — Entry point
├── config.py        — All settings (thresholds, API URLs)
├── weather.py       — Unified forecast fetcher (NOAA + Open-Meteo)
├── polymarket.py    — Fetches weather section, extracts cities dynamically
├── signals.py       — Generates BUY / AVOID / CONVICTION signals
├── scheduler.py     — Runs a scan every 2 minutes
├── telegram_bot.py  — Bot commands + signal delivery
├── requirements.txt — Python dependencies
├── Procfile         — Tells Railway how to start
└── railway.json     — Railway deployment config
```

---

## Deploy on Railway

### Step 1 — Telegram Setup
1. Message **@BotFather** → `/newbot` → copy your **bot token**
2. Message **@userinfobot** → `/start` → copy your **chat ID**
3. Open your new bot in Telegram and send `/start`

### Step 2 — GitHub
1. **github.com** → New repository → name it `weatherbot`
2. **Add file → Upload files** → drag all files → **Commit changes**

### Step 3 — Railway
1. **railway.app** → sign in with GitHub
2. **New Project → Deploy from GitHub repo** → select `weatherbot`
3. Go to **Variables** tab → add:

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | From @userinfobot |

4. Hit **Deploy** — live 24/7.

---

## Optional Variables

| Variable | Default | Meaning |
|---|---|---|
| `ENTRY_THRESHOLD` | `0.15` | BUY when bucket priced below this |
| `EXIT_THRESHOLD` | `0.45` | AVOID when bucket priced above this |
| `CONVICTION_MIN_EDGE` | `0.10` | Min edge for conviction signals |
| `CONVICTION_MIN_VOL` | `5000` | Min market volume for conviction signals |
| `SCAN_INTERVAL_SECONDS` | `120` | Scan frequency |
| `MAX_SIGNALS_PER_SCAN` | `5` | Max alerts per scan |
| `MAX_POSITION_USD` | `2.00` | Suggested size in signal |

---

## Telegram Commands

| Command | What it does |
|---|---|
| `/start` | Welcome & intro |
| `/status` | Last scan time, total signals |
| `/cities` | Cities currently active on Polymarket |
| `/config` | Current thresholds & settings |
| `/lastsignals` | Replay last scan's signals |
| `/help` | Help menu |

---

## Weather Sources

| Source | Coverage | Auth |
|---|---|---|
| NOAA weather.gov | US cities only | None (free) |
| Open-Meteo | Global (150+ countries) | None (free) |

---

## Disclaimer
For informational purposes only. Does not execute trades.
Not financial advice. Always do your own research.
