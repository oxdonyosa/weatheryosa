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

## Deploy on Railway (Recommended)

### Step 1 — Create a Telegram Bot
1. Open Telegram → search **@BotFather** → send `/newbot`
2. Follow the prompts → copy your **bot token**
3. Search **@userinfobot** → send `/start` → copy your **chat ID** (a number)
4. Find your new bot in Telegram and send it `/start` to activate the chat

### Step 2 — Upload to GitHub
1. Go to **github.com** → create a free account
2. Click **New repository** → name it `weatherbot` → Public or Private
3. Upload all these files to the repository

### Step 3 — Deploy on Railway
1. Go to **railway.app** → sign in with GitHub
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your `weatherbot` repository
4. Railway detects Python automatically and starts building

### Step 4 — Add Environment Variables
In your Railway project → **Variables** tab → add these:

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | `your_bot_token_from_BotFather` |
| `TELEGRAM_CHAT_ID` | `your_numeric_chat_id` |

Optional overrides:

| Variable | Default | Meaning |
|---|---|---|
| `ENTRY_THRESHOLD` | `0.15` | Signal when below 15% |
| `EXIT_THRESHOLD` | `0.45` | Signal when above 45% |
| `SCAN_INTERVAL_SECONDS` | `120` | Scan every 2 minutes |
| `MAX_SIGNALS_PER_SCAN` | `5` | Max alerts per scan |
| `MAX_POSITION_USD` | `2.00` | Suggested size in signal |

### Step 5 — Deploy
Click **Deploy** — your bot is live 24/7. Railway auto-restarts it if it crashes.

---

## Telegram Commands

| Command | What it does |
|---|---|
| `/start` | Welcome & intro |
| `/status` | Last scan time, total signals sent |
| `/config` | Show current thresholds |
| `/cities` | List of monitored cities |
| `/lastsignals` | Replay signals from last scan |
| `/help` | Help menu |

---

## Signal Example

```
🟢 BUY SIGNAL 🔥

📍 City: New York City
🌡️ NOAA Forecast: High 58°F / Low 44°F
☁️ Conditions: Partly Cloudy

📊 Market:
Will NYC high temperature be 55-60°F on March 20?

🎯 Bucket: 55-60°F
💰 Price: 9%
📉 Why: NOAA says this bucket resolves ✅ YES
        but market only prices it at 9%
        Edge: 6.0% below 15% entry threshold
💵 Suggested Size: $2.00
📦 Volume: $12,450

🔗 Open on Polymarket
⏰ 2026-03-19 14:32 UTC
⚠️ Signal only — not financial advice. DYOR.
```

---

## Cities Monitored

New York City · Chicago · Seattle · Atlanta · Dallas · Miami

---

## APIs Used (both free, no key needed)

| API | Docs |
|---|---|
| NOAA weather.gov | https://www.weather.gov/documentation/services-web-api |
| Polymarket Gamma | https://gamma-api.polymarket.com |

---

## Disclaimer
For informational purposes only. Does not execute trades.
Not financial advice. Always do your own research before trading.
