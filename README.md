# ResyWatch Bot

A Telegram bot that monitors Resy for open restaurant reservations and alerts you with direct booking links.

**You control it entirely through Telegram.** Message the bot to add/remove watches. It polls in the background and texts you the instant a table opens up. You tap the link and book manually.

## How It Works

```
You: /watch Don Angie, Apr 11-12, 2, 7-9pm
Bot: ✅ Watch #1 added — Don Angie, Apr 11-12, party of 2, 7-9pm

[5 minutes later]
Bot: 🚨 TABLE FOUND
     🍽 Don Angie
     📅 Friday, Apr 11
     🕐 7:30 PM
     👥 Party of 2
     🔗 Book now → https://resy.com/cities/new-york-ny/don-angie?date=2025-04-11&seats=2
```

## Commands

| Command | What it does |
|---------|-------------|
| `/watch <restaurant>, <dates>, <party size>, <time>` | Add a watch |
| `/list` | Show active watches |
| `/remove <#>` | Remove a watch |
| `/search <name>` | Look up a restaurant on Resy |
| `/pause` | Pause all monitoring |
| `/resume` | Resume monitoring |
| `/help` | Show usage examples |

### Watch Format Examples

```
/watch Don Angie, Apr 11-12, 2, 7-9pm
/watch Carbone, any Friday in April, 2, 8-9:30pm
/watch 4 Charles Prime Rib, May 3, 4, 6:30-8pm
/watch Le Bernardin, May 1-15, 2, 7-9pm
/watch Via Carota, Saturdays in May, 2, 7:30-9pm
```

You can also type `watch ...` without the slash.

## Setup (15 minutes)

### 1. Create a Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Name it something like "ResyWatch"
4. Copy the bot token (looks like `7123456789:AAF...`)

### 2. Get Your Chat ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. It replies with your chat ID (a number like `123456789`)
3. This ensures only YOU get the alerts

### 3. Get a Resy API Key (Optional)

The bot ships with a default public API key that works for reading availability. For better reliability, grab your own:

1. Go to [resy.com](https://resy.com) and log in
2. Open browser DevTools (F12) → Network tab
3. Search for any restaurant, find a request to `api.resy.com`
4. Copy the `Authorization` header value (looks like `ResyAPI api_key="..."`)

### 4. Deploy to Railway (Free Tier)

1. Push this repo to a **private** GitHub repository
2. Go to [railway.com](https://railway.com) and sign in with GitHub
3. Click **New Project** → **Deploy from GitHub Repo** → select your repo
4. Go to **Variables** tab and add:

| Variable | Value |
|----------|-------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from step 1 |
| `TELEGRAM_CHAT_ID` | Your chat ID from step 2 |
| `CHECK_INTERVAL_SECONDS` | `300` (5 min, adjust as needed) |

5. Railway auto-deploys. Your bot is live.

### 4b. Alternative: Run Locally

```bash
cp .env.example .env
# Edit .env with your values

pip install -r requirements.txt
cd src && python bot.py
```

### 4c. Alternative: Fly.io

```bash
# Install flyctl, then:
fly launch --name resywatch --region ewr
fly secrets set TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx
fly deploy
```

## Architecture

```
Telegram ←→ Bot (python-telegram-bot)
                ├── Parser (regex-based NLP)
                ├── Storage (SQLite)
                └── Checker (Resy API poller)
                     └── Alerts → Telegram
```

- **Bot**: Handles your Telegram commands, runs a background job on a timer
- **Parser**: Converts natural language like "Fridays in April" into structured date lists
- **Storage**: SQLite file — persists watches and notification history across restarts
- **Checker**: Hits Resy's `/4/find` endpoint for each watch, filters by your time window
- **Alerts**: Sends you a Telegram message with restaurant, date, time, and booking link

## Cost

- **Railway free tier**: 500 hours/month (enough for always-on)
- **Resy API**: Free (public read-only endpoint, no auth needed for availability)
- **Telegram**: Free
- **Total: $0/month** on free tier. If you exceed Railway free tier, it's ~$5/month.

## How Resy's API Works

The bot uses Resy's public `/4/find` endpoint:

```
GET https://api.resy.com/4/find
    ?venue_id=123
    &day=2025-04-11
    &party_size=2
    &lat=0
    &long=0
```

This returns all available time slots with config tokens. No authentication is needed for reading availability. The bot only reads data. It never books anything on your behalf.

## Rate Limiting

Resy doesn't appear to enforce strict rate limits on the find endpoint, but the bot is conservative by default (every 5 minutes). You can adjust `CHECK_INTERVAL_SECONDS`:

- `300` (5 min) — Good default, won't trigger any limits
- `120` (2 min) — More aggressive, fine for a few watches
- `60` (1 min) — Use sparingly, only for high-priority reservations

## Adding OpenTable Support (Future)

The architecture supports multiple platforms. OpenTable's availability can be checked via their public-facing widget endpoints. This is on the roadmap but Resy covers most hard-to-book NYC restaurants.

## Troubleshooting

**Bot doesn't respond:**
- Check that `TELEGRAM_BOT_TOKEN` is correct
- Make sure you messaged the bot first (it can't initiate conversations)

**No results for /search:**
- Try adding the city: `/search Don Angie NYC`
- Some restaurants use slightly different names on Resy

**Not getting alerts:**
- Run `/list` to confirm watches are active (🟢 = active, ⏸ = paused)
- Check that your dates haven't passed
- Verify `TELEGRAM_CHAT_ID` is correct

**Railway keeps restarting:**
- Check logs in Railway dashboard for errors
- Ensure all environment variables are set

## License

MIT. Use it to get great tables. Don't use it to hoard reservations.
