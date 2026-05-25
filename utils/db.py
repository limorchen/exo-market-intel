import sqlite3
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
    new_cols = [("products", "TEXT"), ("recent_deal", "TEXT")]
    with get_conn() as conn:
        for col, col_type in new_cols:
            try:
                conn.execute(f"ALTER TABLE entity_registry ADD COLUMN {col} {col_type}")
            except Exception:
                pass
