"""
ResyWatch Bot — Telegram bot that monitors restaurant availability
across Resy, SevenRooms, and OpenTable.
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
from restaurant_lookup import (
    search_restaurant,
    resolve_venue_from_url,
    detect_platform_from_url,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
RESY_API_KEY = os.environ.get("RESY_API_KEY", 'ResyAPI api_key="VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"')
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "300"))

PLATFORM_EMOJI = {
    "resy": "🟠",
    "sevenrooms": "🔵",
    "opentable": "🔴",
}

PLATFORM_LABELS = {
    "resy": "Resy",
    "sevenrooms": "SevenRooms",
    "opentable": "OpenTable",
}


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🍽 *ResyWatch Bot*\n\n"
        "I monitor Resy, OpenTable, and SevenRooms for open tables "
        "and alert you with booking links.\n\n"
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
        "You can also paste a booking URL:\n"
        "`/watch https://resy.com/cities/new-york-ny/don-angie, Apr 11, 2, 7-9pm`\n"
        "`/watch https://www.sevenrooms.com/reservations/berenjakjks, Apr 18, 2, 7-9pm`\n"
        "`/watch https://www.opentable.com/r/gramercy-tavern-new-york, May 1, 4, 7-9pm`",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use ResyWatch*\n\n"
        "*Supported platforms:*\n"
        "🟠 Resy\n"
        "🔵 SevenRooms\n"
        "🔴 OpenTable\n\n"
        "*Adding a watch by name:*\n"
        "`/watch Don Angie, Apr 11-12, 2, 7-9pm`\n"
        "`/watch Carbone, Fridays in April, 2, 8-9:30pm`\n"
        "`/watch Le Bernardin, May 1-15, 2, 7-9pm`\n\n"
        "*Using a booking URL (any platform):*\n"
        "`/watch https://resy.com/cities/new-york-ny/don-angie, Apr 11, 2, 7-9pm`\n"
        "`/watch https://www.sevenrooms.com/reservations/berenjakjks, Apr 18, 2, 7-9pm`\n"
        "`/watch https://www.opentable.com/r/gramercy-tavern-new-york, May 1, 4, 7-9pm`\n\n"
        "*Searching:*\n"
        "`/search Don Angie`\n"
        "`/search Berenjak` _(auto-detects platform)_\n\n"
        "*Managing watches:*\n"
        "`/list` — see all active watches\n"
        "`/remove 2` — remove watch #2\n"
        "`/pause` / `/resume` — toggle monitoring",
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
            "`/watch https://resy.com/cities/new-york-ny/carbone, Apr 11, 2, 8-9:30pm`\n"
            "`/watch https://www.sevenrooms.com/reservations/berenjakjks, Apr 18, 2, 7-9pm`",
            parse_mode="Markdown",
        )
        return

    parts = [p.strip() for p in raw_text.split(",")]
    first_part = parts[0]

    # Detect if first part is a URL
    is_url = first_part.startswith("http")
    detected_platform = detect_platform_from_url(first_part) if is_url else None

    try:
        watch = parse_watch_command(raw_text)
    except ValueError as e:
        await update.message.reply_text(f"❌ Couldn't parse that: {e}")
        return

    # ── Resolve venue from URL ──────────────────────────────────────────
    if is_url and detected_platform:
        platform_label = PLATFORM_LABELS.get(detected_platform, detected_platform)
        await update.message.reply_text(f"🔍 Looking up restaurant on {platform_label}...")

        venue = await resolve_venue_from_url(first_part, api_key=RESY_API_KEY)
        if venue:
            watch["venue_id"] = venue["id"]
            watch["platform"] = venue["platform"]
            watch["venue_display"] = venue["name"]
            watch["platform_data"] = venue.get("platform_data", {})
            # Preserve Resy-specific fields for backward compat
            if venue["platform"] == "resy":
                watch["resy_url_slug"] = venue.get("url_slug", "")
                watch["location_slug"] = venue.get("platform_data", {}).get("location_slug", "new-york-ny")
        else:
            await update.message.reply_text(
                f"⚠️ Couldn't resolve that URL on {platform_label}.\n"
                f"Try `/search <restaurant name>` instead."
            )
            return

    # ── Search by name ──────────────────────────────────────────────────
    elif not watch.get("venue_id"):
        await update.message.reply_text(f"🔍 Searching for \"{watch['restaurant_name']}\"...")
        results = await search_restaurant(watch["restaurant_name"], RESY_API_KEY)

        if results:
            best = results[0]
            watch["venue_id"] = best["id"]
            watch["platform"] = best.get("platform", "resy")
            watch["venue_display"] = best.get("name", watch["restaurant_name"])
            watch["platform_data"] = best.get("platform_data", {})

            if best.get("platform") == "resy":
                watch["resy_url_slug"] = best.get("url_slug", "")
                watch["location_slug"] = best.get("platform_data", {}).get("location_slug", "new-york-ny")
        else:
            await update.message.reply_text(
                f"⚠️ Couldn't find \"{watch['restaurant_name']}\" on any platform.\n\n"
                f"Try:\n"
                f"• `/search {watch['restaurant_name']}` to browse results\n"
                f"• Paste the booking URL directly (Resy, OpenTable, or SevenRooms)\n"
                f"• Use a venue ID: `/watch id:1234, Apr 11, 2, 7-9pm`",
                parse_mode="Markdown",
            )
            return

    watch_id = storage.add_watch(watch)
    dates_str = ", ".join(watch["dates"][:5])
    if len(watch["dates"]) > 5:
        dates_str += f" (+{len(watch['dates']) - 5} more)"
    time_str = f"{watch['time_min']}-{watch['time_max']}"

    platform_name = watch.get("platform", "resy")
    emoji = PLATFORM_EMOJI.get(platform_name, "⚪")
    label = PLATFORM_LABELS.get(platform_name, platform_name)

    await update.message.reply_text(
        f"✅ *Watch #{watch_id} added*\n\n"
        f"🍽 {watch.get('venue_display', watch['restaurant_name'])}\n"
        f"{emoji} {label}\n"
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
        platform_name = w.get("platform", "resy")
        emoji = PLATFORM_EMOJI.get(platform_name, "⚪")
        label = PLATFORM_LABELS.get(platform_name, platform_name)

        lines.append(
            f"{status} *#{w['id']}* — {w.get('venue_display', w['restaurant_name'])}\n"
            f"   {emoji} {label} | 📅 {dates_str} | 👥 {w['party_size']} | 🕐 {w['time_min']}-{w['time_max']}"
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
        await update.message.reply_text(
            "Usage: `/search <restaurant name>`\nExample: `/search Don Angie`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(f"🔍 Searching for \"{query}\" across platforms...")

    try:
        results = await search_restaurant(query, RESY_API_KEY)
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text(f"❌ Search failed: {e}")
        return

    if not results:
        await update.message.reply_text(
            f"No results for \"{query}\" on Resy, OpenTable, or SevenRooms.\n\n"
            f"Tips:\n"
            f"• Try the exact restaurant name\n"
            f"• Paste the booking URL directly in your `/watch` command"
        )
        return

    lines = [f"🔎 *Results for \"{query}\":*\n"]
    for r in results[:5]:
        platform_name = r.get("platform", "unknown")
        emoji = PLATFORM_EMOJI.get(platform_name, "⚪")
        label = PLATFORM_LABELS.get(platform_name, platform_name)
        name = r.get("name", "Unknown")
        location = r.get("location", "")

        lines.append(
            f"• {emoji} *{name}* ({label})\n"
            f"  {location}\n"
            f"  ID: `{r.get('id', '')}` | Slug: `{r.get('url_slug', '')}`"
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
        return

    # Detect booking platform URLs in plain messages
    platform = detect_platform_from_url(text)
    if platform:
        label = PLATFORM_LABELS.get(platform, platform)
        await update.message.reply_text(
            f"Looks like a {label} link. Use it in a watch command:\n"
            f"`/watch {text}, Apr 18, 2, 7-9pm`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        "I didn't understand that. Try `/help` for usage examples.",
        parse_mode="Markdown",
    )


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
        platform_name = alert.get("platform", "resy")
        emoji = PLATFORM_EMOJI.get(platform_name, "⚪")
        label = PLATFORM_LABELS.get(platform_name, platform_name)

        msg = (
            f"🚨 *TABLE FOUND*\n\n"
            f"🍽 *{alert['restaurant']}*\n"
            f"{emoji} {label}\n"
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

        storage.mark_notified(
            alert["watch_id"],
            alert["date_raw"],
            alert["time_raw"],
            platform=platform_name,
        )

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

    logger.info(f"ResyWatch bot starting (multi-platform). Polling every {CHECK_INTERVAL_SECONDS}s.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
