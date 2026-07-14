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
    entity_cols = [
        ("products", "TEXT"),
        ("recent_deal", "TEXT"),
        ("gtm_score", "REAL"),
        ("pricing_tier", "TEXT DEFAULT 'unknown'"),
        ("supplier_openness", "TEXT DEFAULT 'unknown'"),
        ("brands_carried", "TEXT"),
    ]
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

    _backfill_gtm_scores()
    _backfill_brands_carried()


def _backfill_brands_carried() -> None:
    """One-time fill of brands_carried for entities with researched values in
    data/entities.py — INSERT OR IGNORE in seed_entities never touches rows
    that already exist, so already-seeded databases need this explicit UPDATE."""
    from data.entities import entities

    with get_conn() as conn:
        for ent in entities:
            brands = ent.get("brands_carried")
            if not brands:
                continue
            conn.execute(
                "UPDATE entity_registry SET brands_carried=? "
                "WHERE name=? AND (brands_carried IS NULL OR brands_carried='')",
                (brands, ent["name"]),
            )


def _backfill_gtm_scores() -> None:
    from utils.scoring import calculate_gtm_score

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, states, current_exosome_use, notes, products, priority_score, "
            "ind_seeking, pricing_tier FROM entity_registry WHERE gtm_score IS NULL"
        ).fetchall()
        for row in rows:
            gtm = calculate_gtm_score(
                row["states"], row["current_exosome_use"], row["notes"], row["products"],
                row["priority_score"], row["ind_seeking"], conn, row["pricing_tier"],
            )
            conn.execute("UPDATE entity_registry SET gtm_score=? WHERE id=?", (gtm, row["id"]))


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
