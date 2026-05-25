"""Seed state_registry from data/states_seed.csv."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_conn, init_db

CSV_PATH = Path(__file__).parent.parent / "data" / "states_seed.csv"


def _parse_date(val: str) -> str:
    if not val or val.strip().upper() == "NA":
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(val.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return val.strip()


def seed_states():
    init_db()
    today = datetime.now(timezone.utc).date().isoformat()

    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)

    with get_conn() as conn:
        for _, row in df.iterrows():
            conn.execute(
                """INSERT OR REPLACE INTO state_registry
                   (state_code, state_name, legislation_type, key_provisions, effective_date,
                    physician_admin_allowed, wellness_allowed, aesthetics_allowed,
                    risk_level, notes, source_url, last_updated)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["state_code"].strip(),
                    row["state_name"].strip(),
                    row["legislation_type"].strip(),
                    row["key_provisions"].strip(),
                    _parse_date(row["effective_date"]),
                    int(row["physician_admin_allowed"] or 0),
                    int(row["wellness_allowed"] or 0),
                    int(row["aesthetics_allowed"] or 0),
                    row["risk_level"].strip(),
                    row["notes"].strip(),
                    row["source_url"].strip(),
                    today,
                ),
            )

    counts: dict[str, int] = df["risk_level"].value_counts().to_dict()
    print(f"\nSeeded {len(df)} states from {CSV_PATH.name}:")
    for lvl, n in sorted(counts.items()):
        print(f"  {lvl}: {n}")


if __name__ == "__main__":
    seed_states()
