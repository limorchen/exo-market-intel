import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "exo_market.db"
SCHEMA_PATH = Path(__file__).parent.parent / "db" / "schema.sql"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text()
    with get_conn() as conn:
        conn.executescript(schema)
    _migrate_db()


def _migrate_db() -> None:
    entity_cols = [("products", "TEXT"), ("recent_deal", "TEXT")]
    log_cols = [("entity_name", "TEXT")]
    with get_conn() as conn:
        for col, col_type in entity_cols:
            try:
                conn.execute(f"ALTER TABLE entity_registry ADD COLUMN {col} {col_type}")
            except Exception:
                pass
        for col, col_type in log_cols:
            try:
                conn.execute(f"ALTER TABLE update_log ADD COLUMN {col} {col_type}")
            except Exception:
                pass


def log_change(
    conn: sqlite3.Connection,
    entity_name: str,
    change_type: str,
    description: str,
    logged_by: str = "pipeline",
) -> None:
    """Write a row to update_log. Works even if the entity was just deleted."""
    row = conn.execute("SELECT id FROM entity_registry WHERE name=?", (entity_name,)).fetchone()
    entity_id = row[0] if row else None
    conn.execute(
        """INSERT INTO update_log (entity_id, entity_name, log_date, change_type, description, logged_by)
           VALUES (?,?,?,?,?,?)""",
        (entity_id, entity_name, datetime.now(timezone.utc).isoformat(), change_type, description, logged_by),
    )
