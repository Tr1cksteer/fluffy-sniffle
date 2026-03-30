"""
Database layer — SQLite
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "logoper.db"


def get_db_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS vessels (
                imo         TEXT PRIMARY KEY,
                name        TEXT DEFAULT '',
                line        TEXT DEFAULT '',
                basin       TEXT DEFAULT '',
                current_port TEXT DEFAULT '',
                destination TEXT DEFAULT '',
                last_seen   TEXT DEFAULT '',
                raw_json    TEXT DEFAULT '{}',
                updated_at  TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT DEFAULT ''
            );

            INSERT OR IGNORE INTO meta (key, value) VALUES ('last_update', '—');
        """)
        conn.commit()
    finally:
        conn.close()
