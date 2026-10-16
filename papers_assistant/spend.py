"""Track what the assistant spends on the Claude API, from each response's token usage.

Anthropic offers no API that returns an account's remaining credit (the Usage and
Cost Admin API reports spend, not balance, and needs an admin key, which individual
accounts can't create). So the app prices its own usage and, given the amount and
date of the last top-up, estimates what's left. Other uses of the same Anthropic
organization (other apps, the Console playground) aren't counted.
"""
from datetime import datetime, timezone

# USD per million tokens, from https://platform.claude.com/docs/en/about-claude/pricing
# (fetched 2026-10-16). Cache writes use the 5-minute rate: the app's caching is 5-minute.
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "cache_write": 5.00, "cache_read": 0.20, "output": 20.00},
    "claude-sonnet-5-5": {"input": 2.00, "cache_write": 2.50, "cache_read": 0.10, "output": 10.00},
    "claude-haiku-5-5": {"input": 0.10, "cache_write": 0.125, "cache_read": 0.01, "output": 0.50},
}
# Claude Haiku 5.5 charges more when a request's prompt is over 100,000 tokens.
HAIKU_LONG = {"input": 0.50, "cache_write": 0.625, "cache_read": 0.05, "output": 2.50}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_usage (
    ts          TEXT NOT NULL,     -- UTC ISO time
    question_id TEXT,              -- groups the API calls of one question
    user        TEXT,
    kind        TEXT,              -- 'answer' or 'status'
    model       TEXT,
    input       INTEGER,
    cache_write INTEGER,
    cache_read  INTEGER,
    output      INTEGER,
    cost_usd    REAL               -- NULL if the model's price is unknown
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_ts ON ai_usage(ts);
"""


def _tokens(usage):
    get = lambda name: int(getattr(usage, name, 0) or 0)  # noqa: E731
    return {"input": get("input_tokens"), "cache_write": get("cache_creation_input_tokens"),
            "cache_read": get("cache_read_input_tokens"), "output": get("output_tokens")}


def cost_usd(model, tokens):
    """Price one API response; None if the model isn't in PRICES."""
    prices = PRICES.get(model)
    if prices is None:
        return None
    if model == "claude-haiku-5-5" and tokens["input"] + tokens["cache_write"] + tokens["cache_read"] > 100_000:
        prices = HAIKU_LONG
    return sum(tokens[k] * prices[k] for k in prices) / 1_000_000


def record(conn, question_id, user, kind, model, usage):
    """Log one API response's usage and cost."""
    tokens = _tokens(usage)
    conn.execute(
        "INSERT INTO ai_usage (ts, question_id, user, kind, model, input, cache_write, cache_read, output, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), question_id, user, kind, model,
         tokens["input"], tokens["cache_write"], tokens["cache_read"], tokens["output"], cost_usd(model, tokens)),
    )
    conn.commit()


def spent_since(conn, since_iso):
    """(dollars spent, questions answered, API calls with an unknown price) since a UTC ISO time."""
    cost, questions, unpriced = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0), COUNT(DISTINCT CASE WHEN kind = 'answer' THEN question_id END), "
        "SUM(cost_usd IS NULL) FROM ai_usage WHERE ts >= ?", (since_iso,)).fetchone()
    return float(cost), int(questions or 0), int(unpriced or 0)


def month_start_iso():
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
