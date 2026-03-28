# ResyWatch

Telegram bot that monitors restaurant availability across **Resy**, **OpenTable**, and **SevenRooms** and alerts you when tables open up.

## How it works

1. You tell the bot which restaurants, dates, party size, and time window you want
2. The bot polls the booking platform every 5 minutes
3. When a matching table opens up, you get a Telegram notification with a direct booking link

## Supported platforms

| Platform | Detection | Search | Availability | Booking Link |
|----------|-----------|--------|-------------|-------------|
| 🟠 Resy | URL + name search | Resy API | Resy `/4/find` | Direct |
| 🔵 SevenRooms | URL + Google detect | Google fallback | Widget API | Direct |
| 🔴 OpenTable | URL + name search | OT search API | REST + GQL | Direct |

## Usage

```
/watch Don Angie, Apr 11-12, 2, 7-9pm
/watch Carbone, Fridays in April, 2, 8-9:30pm
/watch https://www.sevenrooms.com/reservations/berenjakjks, Apr 18, 2, 7-9pm
/watch https://www.opentable.com/r/gramercy-tavern-new-york, May 1, 4, 7-9pm
/search Berenjak
/list
/remove 2
/pause
/resume
```

The bot auto-detects which platform a restaurant is on. If you search by name, it checks Resy first, then OpenTable, then tries Google to detect SevenRooms venues.

If you paste a booking URL, it extracts the venue slug and routes to the correct platform automatically.

## Setup

### Environment variables

```
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
RESY_API_KEY=ResyAPI api_key="VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"
CHECK_INTERVAL_SECONDS=300
DB_PATH=resywatch.db
```

### Run locally

```bash
pip install -r requirements.txt
python bot.py
```

### Deploy to Railway

```bash
railway up
```

The included `Dockerfile` and `railway.toml` handle deployment. Set your env vars in the Railway dashboard.

## Architecture

```
bot.py                  — Telegram bot commands and polling loop
checker.py              — Routes watches to platform checkers, filters by time window
parser.py               — Natural language date/time parsing
storage.py              — SQLite persistence with auto-migration
restaurant_lookup.py    — Multi-platform search + Google auto-detection

platforms/
  __init__.py           — Platform registry
  base.py               — Abstract base class
  resy.py               — Resy API checker
  sevenrooms.py         — SevenRooms widget API checker
  opentable.py          — OpenTable REST/GQL checker
```

## Adding a new platform

1. Create `platforms/newplatform.py` implementing `BasePlatform`
2. Add it to the registry in `platforms/__init__.py`
3. Add URL detection in `restaurant_lookup.py:detect_platform_from_url()`
4. Add emoji/label in `bot.py`
