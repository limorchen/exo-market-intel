from __future__ import annotations
import sqlite3


_LEGISLATION_SCORE = {"low": 10, "medium": 6, "high": 3, "unknown": 2, "unclear": 2}

_REACH_LARGE_STATES = {
    "CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI",
}


def _legislation_score(states_str: str | None, conn: sqlite3.Connection) -> float:
    if not states_str:
        return 2.0
    codes = [s.strip().upper() for s in states_str.split(",") if s.strip() and s.strip() != "INTL"]
    if not codes:
        return 2.0
    rows = conn.execute(
        f"SELECT risk_level FROM state_registry WHERE state_code IN ({','.join('?' * len(codes))})",
        codes,
    ).fetchall()
    if not rows:
        return 2.0
    scores = [_LEGISLATION_SCORE.get((r["risk_level"] or "unknown").lower(), 2) for r in rows]
    return max(scores)


def _reach_score(states_str: str | None) -> float:
    if not states_str:
        return 2.0
    codes = {s.strip().upper() for s in states_str.split(",") if s.strip()}
    real_codes = {c for c in codes if c != "INTL"}
    if len(real_codes) > 1:
        return 10.0
    if len(real_codes) == 1:
        code = next(iter(real_codes))
        return 7.0 if code in _REACH_LARGE_STATES else 4.0
    return 2.0


def _engagement_score(engagement: str | None) -> float:
    return {"active": 10.0, "interested": 7.0, "adjacent": 4.0, "unknown": 2.0}.get(
        (engagement or "unknown").lower(), 2.0
    )


def _contact_score(website: str | None, contact_info: str | None) -> float:
    has_web = bool(website and website.strip())
    has_contact = bool(contact_info and contact_info.strip())
    if has_web and has_contact:
        return 10.0
    if has_web:
        return 6.0
    return 2.0


def calculate_score(
    states: str | None,
    current_exosome_use: str | None,
    website: str | None,
    contact_info: str | None,
    ind_seeking: int,
    conn: sqlite3.Connection,
) -> float:
    if ind_seeking:
        return 0.0
    leg = _legislation_score(states, conn)
    reach = _reach_score(states)
    eng = _engagement_score(current_exosome_use)
    contact = _contact_score(website, contact_info)
    raw = leg * 0.35 + reach * 0.25 + eng * 0.25 + contact * 0.15
    return round(min(max(raw, 1.0), 10.0), 2)
