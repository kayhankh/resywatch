"""
ResyWatch Bot — Telegram bot that monitors restaurant availability on Resy & OpenTable.

Usage:
    /watch Don Angie, Apr 11-12, 2, 7-9pm
    /list
    /remove 1
    /search Don Angie
    /help
"""

import logging
import os
import asyncio
from datetime import datetime, time

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from parser import parse_watch_command
from checker import check_all_watches
from storage import Storage
from restaurant_lookup import search_restaurant

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]  # Your personal chat ID
RESY_API_KEY = os.environ.get("RESY_API_KEY", "ResyAPI api_key=\"VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5\"")
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "300"))  # 5 min default


# ── Command Handlers ────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message."""
    await update.message.reply_text(
        "🍽 *ResyWatch Bot*\n\n"
        "I'll watch restaurants for open tables and alert you.\n\n"
        "*Commands:*\n"
        "`/watch` — Add a restaurant watch\n"
        "`/list` — Show active watches\n"
        "`/remove <#>` — Remove a watch\n"
        "`/search <name>` — Look up a restaurant ID\n"
        "`/pause` — Pause all monitoring\n"
        "`/resume` — Resume monitoring\n"
        "`/help` — Show usage examples\n\n"
        "*Watch format:*\n"
        "`/watch <restaurant>, <dates>, <party size>, <time range>`\n\n"
        "*Examples:*\n"
        "`/watch Don Angie, Apr 11-12, 2, 7-9pm`\n"
        "`/watch Carbone, any Friday in April, 2, 8-9:30pm`\n"
        "`/watch 4 Charles Prime Rib, May 3, 4, 6:30-8pm`",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed help."""
    await update.message.reply_text(
        "📖 *How to use ResyWatch*\n\n"
        "*Adding a watch:*\n"
        "`/watch Don Angie, Apr 11-12, 2, 7-9pm`\n"
        "`/watch Carbone, Fridays in April, 2, 8-9:30pm`\n"
        "`/watch Le Bernardin, May 1-15, 2, 7-9pm`\n\n"
        "*Searching for restaurants:*\n"
        "`/search Don Angie` — finds venue ID and platform\n"
        "`/search Carbone NYC` — add city for better results\n\n"
        "*Managing watches:*\n"
        "`/list` — see all active watches\n"
        "`/remove 2` — remove watch #2\n"
        "`/pause` — pause monitoring\n"
        "`/resume` — resume monitoring\n\n"
        "*Supported platforms:* Resy (auto-detected)\n"
        "*Alerts:* You'll get a message with a direct booking link\n"
        "*Booking:* You tap the link and book manually",
        parse_mode="Markdown",
    )


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parse and add a new restaurant watch."""
    storage: Storage = context.bot_data["storage"]
    raw_text = update.message.text.replace("/watch", "", 1).strip()

    if not raw_text:
        await update.message.reply_text(
            "Usage: `/watch <restaurant>, <dates>, <party size>, <time range>`\n"
            "Example: `/watch Don Angie, Apr 11-12, 2, 7-9pm`",
            parse_mode="Markdown",
        )
        return

    try:
        watch = parse_watch_command(raw_text)
    except ValueError as e:
        await update.message.reply_text(f"❌ Couldn't parse that: {e}")
        return

    # Try to auto-resolve venue if not already set
    if not watch.get("venue_id"):
        results = await search_restaurant(watch["restaurant_name"], RESY_API_KEY)
        if results:
            best = results[0]
            watch["venue_id"] = best["id"]
            watch["platform"] = best.get("platform", "resy")
            watch["venue_display"] = best.get("name", watch["restaurant_name"])
            watch["resy_url_slug"] = best.get("url_slug", "")
        else:
            await update.message.reply_text(
                f"⚠️ Couldn't find \"{watch['restaurant_name']}\" on Resy.\n"
                f"Try `/search {watch['restaurant_name']}` to find it manually, "
                f"or add it with a venue ID: `/watch id:1234, Apr 11, 2, 7-9pm`"
            )
            return

    watch_id = storage.add_watch(watch)
    dates_str = ", ".join(watch["dates"]) if isinstance(watch["dates"], list) else watch["dates"]
    time_str = f"{watch['time_min']}-{watch['time_max']}"

    await update.message.reply_text(
        f"✅ *Watch #{watch_id} added*\n"
        f"🍽 {watch.get('venue_display', watch['restaurant_name'])}\n"
        f"📅 {dates_str}\n"
        f"👥 Party of {watch['party_size']}\n"
        f"🕐 {time_str}\n"
        f"🔍 Checking every {CHECK_INTERVAL_SECONDS // 60} min",
        parse_mode="Markdown",
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all active watches."""
    storage: Storage = context.bot_data["storage"]
    watches = storage.get_active_watches()

    if not watches:
        await update.message.reply_text("No active watches. Use `/watch` to add one.", parse_mode="Markdown")
        return

    lines = ["📋 *Active Watches*\n"]
    for w in watches:
        dates_str = ", ".join(w["dates"]) if isinstance(w["dates"], list) else w["dates"]
        status = "⏸" if w.get("paused") else "🟢"
        lines.append(
            f"{status} *#{w['id']}* — {w.get('venue_display', w['restaurant_name'])}\n"
            f"   📅 {dates_str} | 👥 {w['party_size']} | 🕐 {w['time_min']}-{w['time_max']}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a watch by ID."""
    storage: Storage = context.bot_data["storage"]
    raw = update.message.text.replace("/remove", "", 1).strip()

    try:
        watch_id = int(raw)
    except (ValueError, TypeError):
        await update.message.reply_text("Usage: `/remove <watch number>`", parse_mode="Markdown")
        return

    watch = storage.remove_watch(watch_id)
    if watch:
        await update.message.reply_text(
            f"❌ Removed watch #{watch_id} ({watch.get('venue_display', watch.get('restaurant_name', 'Unknown'))})"
        )
    else:
        await update.message.reply_text(f"Watch #{watch_id} not found.")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for a restaurant on Resy."""
    query = update.message.text.replace("/search", "", 1).strip()
    if not query:
        await update.message.reply_text("Usage: `/search <restaurant name>`", parse_mode="Markdown")
        return

    await update.message.reply_text(f"🔍 Searching for \"{query}\"...")

    results = await search_restaurant(query, RESY_API_KEY)
    if not results:
        await update.message.reply_text(f"No results found for \"{query}\". Try adding the city (e.g., \"{query} NYC\").")
        return

    lines = [f"🔎 *Results for \"{query}\":*\n"]
    for r in results[:5]:
        venue_id = r["id"]
        name = r.get("name", "Unknown")
        location = r.get("location", "")
        platform = r.get("platform", "resy")
        lines.append(f"• *{name}* — {location}\n  ID: `{venue_id}` | Platform: {platform}")

    lines.append(f"\nUse the name in your `/watch` command and I'll auto-match it.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause all monitoring."""
    context.bot_data["paused"] = True
    await update.message.reply_text("⏸ Monitoring paused. Use `/resume` to restart.", parse_mode="Markdown")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume monitoring."""
    context.bot_data["paused"] = False
    await update.message.reply_text("▶️ Monitoring resumed.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages as potential watch commands."""
    text = update.message.text.strip().lower()

    # If it looks like a watch command without the slash
    if text.startswith("watch "):
        update.message.text = "/" + update.message.text.strip()
        await cmd_watch(update, context)
    else:
        await update.message.reply_text(
            "I didn't understand that. Try `/help` for usage examples.",
            parse_mode="Markdown",
        )


# ── Background Polling Job ──────────────────────────────────────────────────

async def poll_availability(context: ContextTypes.DEFAULT_TYPE):
    """Periodic job: check all watches for availability."""
    if context.bot_data.get("paused"):
        return

    storage: Storage = context.bot_data["storage"]
    watches = storage.get_active_watches()

    if not watches:
        return

    logger.info(f"Checking availability for {len(watches)} watches...")

    try:
        alerts = await check_all_watches(watches, RESY_API_KEY)
    except Exception as e:
        logger.error(f"Error checking availability: {e}")
        return

    for alert in alerts:
        booking_url = alert.get("booking_url", "")
        msg = (
            f"🚨 *TABLE FOUND*\n\n"
            f"🍽 *{alert['restaurant']}*\n"
            f"📅 {alert['date']}\n"
            f"🕐 {alert['time']}\n"
            f"👥 Party of {alert['party_size']}\n"
            f"💺 {alert.get('table_type', 'Standard')}\n\n"
            f"🔗 [Book now]({booking_url})"
        )
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="Markdown",
            disable_web_page_preview=False,
        )

        # Mark as notified to avoid repeat alerts
        storage.mark_notified(alert["watch_id"], alert["date"], alert["time"])

    if alerts:
        logger.info(f"Sent {len(alerts)} alerts.")


# ── App Setup ───────────────────────────────────────────────────────────────

def main():
    """Start the bot."""
    storage = Storage()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Store shared state
    app.bot_data["storage"] = storage
    app.bot_data["paused"] = False

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))

    # Plain text fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Schedule the availability checker
    job_queue = app.job_queue
    job_queue.run_repeating(
        poll_availability,
        interval=CHECK_INTERVAL_SECONDS,
        first=10,  # Start first check 10 seconds after boot
    )

    logger.info(f"ResyWatch bot starting. Polling every {CHECK_INTERVAL_SECONDS}s.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
