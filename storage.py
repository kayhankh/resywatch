"""
SQLite storage for watch persistence.

Stores watches and notification history so the bot survives restarts
without re-alerting for slots it already told you about.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "resywatch.db")


class Storage:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS watches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    restaurant_name TEXT NOT NULL,
                    venue_id INTEGER,
                    venue_display TEXT,
                    platform TEXT DEFAULT 'resy',
                    dates TEXT NOT NULL,
                    party_size INTEGER NOT NULL,
                    time_min TEXT NOT NULL,
                    time_max TEXT NOT NULL,
                    resy_url_slug TEXT DEFAULT '',
                    paused INTEGER DEFAULT 0,
                    active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    notified_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(watch_id, date, time)
                )
            """)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def add_watch(self, watch: dict) -> int:
        """Add a new watch. Returns the watch ID."""
        dates_json = json.dumps(watch["dates"])

        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO watches
                    (restaurant_name, venue_id, venue_display, platform,
                     dates, party_size, time_min, time_max, resy_url_slug)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    watch.get("restaurant_name", ""),
                    watch.get("venue_id"),
                    watch.get("venue_display", watch.get("restaurant_name", "")),
                    watch.get("platform", "resy"),
                    dates_json,
                    watch["party_size"],
                    watch["time_min"],
                    watch["time_max"],
                    watch.get("resy_url_slug", ""),
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_active_watches(self) -> list[dict]:
        """Get all active (non-removed) watches with their notification history."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM watches WHERE active = 1 ORDER BY id"
            ).fetchall()

        watches = []
        for row in rows:
            watch = dict(row)
            watch["dates"] = json.loads(watch["dates"])
            watch["notified_slots"] = self._get_notified_slots(watch["id"])
            watches.append(watch)

        return watches

    def remove_watch(self, watch_id: int) -> Optional[dict]:
        """Soft-delete a watch. Returns the watch if found."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM watches WHERE id = ? AND active = 1", (watch_id,)
            ).fetchone()

            if not row:
                return None

            watch = dict(row)
            conn.execute(
                "UPDATE watches SET active = 0 WHERE id = ?", (watch_id,)
            )
            conn.commit()
            return watch

    def mark_notified(self, watch_id: int, date: str, time_str: str):
        """Record that we sent an alert for this slot."""
        with self._conn() as conn:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO notifications (watch_id, date, time) VALUES (?, ?, ?)",
                    (watch_id, date, time_str),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                pass  # Already notified

    def _get_notified_slots(self, watch_id: int) -> list[str]:
        """Get list of already-notified slot keys for a watch."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT date, time FROM notifications WHERE watch_id = ?",
                (watch_id,),
            ).fetchall()

        return [f"{row[0]}_{row[1]}" for row in rows]

    def pause_watch(self, watch_id: int) -> bool:
        """Pause a specific watch."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE watches SET paused = 1 WHERE id = ? AND active = 1",
                (watch_id,),
            )
            conn.commit()
            return conn.total_changes > 0

    def resume_watch(self, watch_id: int) -> bool:
        """Resume a specific watch."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE watches SET paused = 0 WHERE id = ? AND active = 1",
                (watch_id,),
            )
            conn.commit()
            return conn.total_changes > 0

    def cleanup_expired(self):
        """Remove watches where all dates are in the past."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, dates FROM watches WHERE active = 1"
            ).fetchall()

            for row in rows:
                watch_id, dates_json = row
                dates = json.loads(dates_json)
                if all(d < today for d in dates):
                    conn.execute(
                        "UPDATE watches SET active = 0 WHERE id = ?",
                        (watch_id,),
                    )
                    logger.info(f"Auto-deactivated expired watch #{watch_id}")

            conn.commit()
