"""Seed entity_registry with initial batch of real commercial entities."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from data.entities import entities
from utils.db import get_conn, init_db, log_change
from utils.scoring import calculate_score


def seed_entities():
    init_db()
    today = datetime.now(timezone.utc).date().isoformat()

    added = 0
    excluded = 0
    score_dist: dict[str, int] = {"0-3": 0, "3-5": 0, "5-7": 0, "7-9": 0, "9-10": 0}

    with get_conn() as conn:
        for ent in entities:
            score = calculate_score(
                ent.get("states"),
                ent.get("current_exosome_use"),
                ent.get("website"),
                ent.get("contact_info"),
                int(ent.get("ind_seeking", 0)),
                conn,
            )

            active = 0 if ent.get("ind_seeking") else 1
            if ent.get("ind_seeking"):
                excluded += 1
            else:
                added += 1

            cur = conn.execute(
                """INSERT OR IGNORE INTO entity_registry
                   (name, entity_type, states, country, us_reach, specialty,
                    current_exosome_use, ind_seeking, website, contact_info,
                    linkedin_url, priority_score, products, recent_deal,
                    notes, source, last_updated, active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ent["name"], ent["entity_type"],
                    ent.get("states", ""), ent.get("country", "US"),
                    int(ent.get("us_reach", 1)),
                    ent.get("specialty", ""),
                    ent.get("current_exosome_use", "unknown"),
                    int(ent.get("ind_seeking", 0)),
                    ent.get("website", ""),
                    ent.get("contact_info", ""),
                    ent.get("linkedin_url", ""),
                    score,
                    ent.get("products", ""),
                    ent.get("recent_deal", ""),
                    ent.get("notes", ""),
                    ent.get("source", "seed"),
                    today, active,
                ),
            )
            if cur.rowcount == 1:
                label = "EXCLUDED — ind_seeking" if ent.get("ind_seeking") else ent["entity_type"]
                log_change(
                    conn, ent["name"], "new",
                    f"Seeded: {ent['name']} | type={label} | score={score}",
                    "seed_entities",
                )

            if score < 3:
                score_dist["0-3"] += 1
            elif score < 5:
                score_dist["3-5"] += 1
            elif score < 7:
                score_dist["5-7"] += 1
            elif score < 9:
                score_dist["7-9"] += 1
            else:
                score_dist["9-10"] += 1

    total = len(entities)
    print(f"\n{'='*50}")
    print(f"Entity seed complete: {total} total")
    print(f"  Active (ind_seeking=0): {added}")
    print(f"  Excluded (ind_seeking=1): {excluded}")
    print("\nScore distribution (active only):")
    for band, n in score_dist.items():
        print(f"  {band}: {n}")

    by_type: dict[str, int] = {}
    for ent in entities:
        t = ent["entity_type"]
        by_type[t] = by_type.get(t, 0) + 1
    print("\nBy type:")
    for t, n in sorted(by_type.items()):
        print(f"  {t}: {n}")


if __name__ == "__main__":
    seed_entities()
