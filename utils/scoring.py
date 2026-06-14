from __future__ import annotations
import re
import sqlite3


_LEGISLATION_SCORE = {"low": 10, "medium": 6, "high": 3, "unknown": 2, "unclear": 2}

_READINESS_SCORE = {"active": 10.0, "interested": 5.0, "adjacent": 3.0, "unknown": 1.0}

_PRICING_TIER_SCORE = {"premium": 10.0, "mid-market": 6.0, "mass": 3.0, "unknown": 2.0}

_LOC_RE = re.compile(
    r"(\d+)\+?\s*(?:US\s+)?(?:confirmed\s+)?(?:US\s+)?(?:clinic|location|practice|center|franchise)",
    re.I,
)

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


def _location_estimate(notes: str | None, products: str | None, states_str: str | None) -> int:
    text = f"{notes or ''} {products or ''}"
    nums = [int(n) for n in _LOC_RE.findall(text)]
    codes = [s.strip() for s in (states_str or "").split(",") if s.strip()]
    n_states = len(codes) if codes else 1
    return max(max(nums), n_states) if nums else n_states


def _scale_score(notes: str | None, products: str | None, states_str: str | None) -> float:
    locs = _location_estimate(notes, products, states_str)
    return round(min(10.0, (locs ** 0.5) * 2.2), 2)


def calculate_gtm_score(
    states: str | None,
    current_exosome_use: str | None,
    notes: str | None,
    products: str | None,
    priority_score: float | None,
    ind_seeking: int,
    conn: sqlite3.Connection,
    pricing_tier: str | None = None,
) -> float:
    """Go-to-market priority: readiness (25%) + scale (15%) + legislation favorability
    (15%) + priority score (15%) + pricing tier (30%).

    Pricing tier carries the heaviest single weight: entities pricing their products/services
    more aggressively (premium) tend to run on better margins and are more open to adopting
    new/improved products — making them better first-wave targets.
    """
    if ind_seeking:
        return 0.0
    readiness = _READINESS_SCORE.get((current_exosome_use or "unknown").lower(), 1.0)
    scale = _scale_score(notes, products, states)
    leg = _legislation_score(states, conn)
    pricing = _PRICING_TIER_SCORE.get((pricing_tier or "unknown").lower(), 2.0)
    raw = (
        readiness * 0.25
        + scale * 0.15
        + leg * 0.15
        + (priority_score or 0.0) * 0.15
        + pricing * 0.30
    )
    return round(min(max(raw, 0.0), 10.0), 2)
