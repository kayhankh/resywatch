"""
ResyWatch Bot — Telegram bot that monitors restaurant availability on Resy.
"""

import logging
import os
import traceback
from datetime import datetime

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
from restaurant_lookup import search_restaurant, resolve_venue_from_url

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
RESY_API_KEY = os.environ.get("RESY_API_KEY", 'ResyAPI api_key="VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"')
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "300"))


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🍽 *ResyWatch Bot*\n\n"
        "I monitor Resy for open tables and alert you with booking links.\n\n"
        "*Commands:*\n"
        "`/watch` — Add a restaurant watch\n"
        "`/list` — Show active watches\n"
        "`/remove <#>` — Remove a watch\n"
        "`/search <name>` — Look up a restaurant\n"
        "`/pause` — Pause monitoring\n"
        "`/resume` — Resume monitoring\n"
        "`/help` — Usage examples\n\n"
        "*Quick start:*\n"
        "`/watch Don Angie, Apr 11-12, 2, 7-9pm`\n\n"
        "You can also paste a Resy URL:\n"
        "`/watch https://resy.com/cities/new-york-ny/don-angie, Apr 11, 2, 7-9pm`",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use ResyWatch*\n\n"
        "*Adding a watch:*\n"
        "`/watch Don Angie, Apr 11-12, 2, 7-9pm`\n"
        "`/watch Carbone, Fridays in April, 2, 8-9:30pm`\n"
        "`/watch Le Bernardin, May 1-15, 2, 7-9pm`\n\n"
        "*Using a Resy URL:*\n"
        "`/watch https://resy.com/cities/new-york-ny/don-angie, Apr 11, 2, 7-9pm`\n\n"
        "*Using a venue ID:*\n"
        "`/watch id:1387, May 3, 2, 7-9pm`\n\n"
        "*Searching:*\n"
        "`/search Don Angie`\n"
        "`/search Carbone`\n\n"
        "*Managing watches:*\n"
        "`/list` — see all active watches\n"
        "`/remove 2` — remove watch #2\n"
        "`/pause` / `/resume` — toggle monitoring\n\n"
        "*Note:* Resy is primarily US-based. London restaurants may not be listed.",
        parse_mode="Markdown",
    )


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage: Storage = context.bot_data["storage"]
    raw_text = update.message.text.replace("/watch", "", 1).strip()

    if not raw_text:
        await update.message.reply_text(
            "Usage: `/watch <restaurant>, <dates>, <party size>, <time range>`\n\n"
            "Examples:\n"
            "`/watch Don Angie, Apr 11-12, 2, 7-9pm`\n"
            "`/watch https://resy.com/cities/new-york-ny/carbone, Apr 11, 2, 8-9:30pm`",
            parse_mode="Markdown",
        )
        return

    parts = [p.strip() for p in raw_text.split(",")]
    is_url = parts[0].startswith("http") and "resy.com" in parts[0]

    try:
        watch = parse_watch_command(raw_text)
    except ValueError as e:
        await update.message.reply_text(f"❌ Couldn't parse that: {e}")
        return

    if is_url:
        await update.message.reply_text("🔍 Looking up restaurant from URL...")
        venue = await resolve_venue_from_url(parts[0], RESY_API_KEY)
        if venue:
            watch["venue_id"] = venue["id"]
            watch["platform"] = "resy"
            watch["venue_display"] = venue["name"]
            watch["resy_url_slug"] = venue.get("url_slug", "")
            watch["location_slug"] = venue.get("location_slug", "new-york-ny")
        else:
            await update.message.reply_text(
                "⚠️ Couldn't resolve that URL. Try `/search <restaurant name>` instead."
            )
            return
    elif not watch.get("venue_id"):
        await update.message.reply_text(f"🔍 Searching for \"{watch['restaurant_name']}\"...")
        results = await search_restaurant(watch["restaurant_name"], RESY_API_KEY)
        if results:
            best = results[0]
            watch["venue_id"] = best["id"]
            watch["platform"] = best.get("platform", "resy")
            watch["venue_display"] = best.get("name", watch["restaurant_name"])
            watch["resy_url_slug"] = best.get("url_slug", "")
            watch["location_slug"] = best.get("location_slug", "new-york-ny")
        else:
            await update.message.reply_text(
                f"⚠️ Couldn't find \"{watch['restaurant_name']}\" on Resy.\n\n"
                f"Try:\n"
                f"• `/search {watch['restaurant_name']}` to browse results\n"
                f"• Paste the Resy URL directly\n"
                f"• Use a venue ID: `/watch id:1234, Apr 11, 2, 7-9pm`\n\n"
                f"Note: Resy is primarily US-based.",
                parse_mode="Markdown",
            )
            return

    watch_id = storage.add_watch(watch)
    dates_str = ", ".join(watch["dates"][:5])
    if len(watch["dates"]) > 5:
        dates_str += f" (+{len(watch['dates']) - 5} more)"
    time_str = f"{watch['time_min']}-{watch['time_max']}"

    await update.message.reply_text(
        f"✅ *Watch #{watch_id} added*\n\n"
        f"🍽 {watch.get('venue_display', watch['restaurant_name'])}\n"
        f"📅 {dates_str}\n"
        f"👥 Party of {watch['party_size']}\n"
        f"🕐 {time_str}\n"
        f"🔍 Checking every {CHECK_INTERVAL_SECONDS // 60} min",
        parse_mode="Markdown",
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage: Storage = context.bot_data["storage"]
    watches = storage.get_active_watches()

    if not watches:
        await update.message.reply_text("No active watches. Use `/watch` to add one.", parse_mode="Markdown")
        return

    paused_global = context.bot_data.get("paused", False)
    lines = ["📋 *Active Watches*\n"]
    if paused_global:
        lines.append("⏸ _Monitoring is paused globally_\n")

    for w in watches:
        dates = w["dates"]
        dates_str = ", ".join(dates[:3])
        if len(dates) > 3:
            dates_str += f" (+{len(dates) - 3} more)"
        status = "⏸" if w.get("paused") else "🟢"
        lines.append(
            f"{status} *#{w['id']}* — {w.get('venue_display', w['restaurant_name'])}\n"
            f"   📅 {dates_str} | 👥 {w['party_size']} | 🕐 {w['time_min']}-{w['time_max']}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    storage: Storage = context.bot_data["storage"]
    raw = update.message.text.replace("/remove", "", 1).strip()

    try:
        watch_id = int(raw)
    except (ValueError, TypeError):
        await update.message.reply_text("Usage: `/remove <watch number>`", parse_mode="Markdown")
        return

    watch = storage.remove_watch(watch_id)
    if watch:
        name = watch.get("venue_display", watch.get("restaurant_name", "Unknown"))
        await update.message.reply_text(f"❌ Removed watch #{watch_id} ({name})")
    else:
        await update.message.reply_text(f"Watch #{watch_id} not found.")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.replace("/search", "", 1).strip()
    if not query:
        await update.message.reply_text("Usage: `/search <restaurant name>`\nExample: `/search Don Angie`", parse_mode="Markdown")
        return

    await update.message.reply_text(f"🔍 Searching Resy for \"{query}\"...")

    try:
        results = await search_restaurant(query, RESY_API_KEY)
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text(f"❌ Search failed: {e}")
        return

    if not results:
        await update.message.reply_text(
            f"No results for \"{query}\".\n\n"
            f"Tips:\n"
            f"• Resy is primarily US-based\n"
            f"• Try the exact restaurant name\n"
            f"• You can paste a Resy URL in your `/watch` command"
        )
        return

    lines = [f"🔎 *Results for \"{query}\":*\n"]
    for r in results[:5]:
        venue_id = r["id"]
        name = r.get("name", "Unknown")
        location = r.get("location", "")
        lines.append(
            f"• *{name}* — {location}\n"
            f"  ID: `{venue_id}` | Slug: `{r.get('url_slug', '')}`"
        )

    lines.append(f"\nUse the restaurant name in `/watch` and I'll auto-match it.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data["paused"] = True
    await update.message.reply_text("⏸ Monitoring paused. Use `/resume` to restart.", parse_mode="Markdown")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data["paused"] = False
    await update.message.reply_text("▶️ Monitoring resumed.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower().startswith("watch "):
        update.message.text = "/" + text
        await cmd_watch(update, context)
    elif "resy.com" in text:
        await update.message.reply_text(
            "Looks like a Resy link. Use it in a watch command:\n"
            f"`/watch {text}, Apr 11, 2, 7-9pm`",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("I didn't understand that. Try `/help` for usage examples.", parse_mode="Markdown")


async def poll_availability(context: ContextTypes.DEFAULT_TYPE):
    if context.bot_data.get("paused"):
        return

    storage: Storage = context.bot_data["storage"]
    storage.cleanup_expired()
    watches = storage.get_active_watches()

    if not watches:
        return

    logger.info(f"Checking availability for {len(watches)} watches...")

    try:
        alerts = await check_all_watches(watches, RESY_API_KEY)
    except Exception as e:
        logger.error(f"Error checking availability: {e}\n{traceback.format_exc()}")
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
        try:
            await context.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=msg,
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

        storage.mark_notified(alert["watch_id"], alert["date_raw"], alert["time_raw"])

    if alerts:
        logger.info(f"Sent {len(alerts)} alerts.")


def main():
    storage = Storage()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.bot_data["storage"] = storage
    app.bot_data["paused"] = False

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = app.job_queue
    job_queue.run_repeating(poll_availability, interval=CHECK_INTERVAL_SECONDS, first=10)

    logger.info(f"ResyWatch bot starting. Polling every {CHECK_INTERVAL_SECONDS}s.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
