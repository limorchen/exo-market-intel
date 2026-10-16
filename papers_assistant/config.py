"""Settings, read from Streamlit secrets first and environment variables second.

See .streamlit/secrets.toml.example for every key.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INDEX_DB = Path(os.environ.get("PAPERS_INDEX_DB", BASE_DIR / "index" / "papers.db"))


def get(key, default=None):
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


DRIVE_FOLDER_ID = get("DRIVE_FOLDER_ID")
ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in str(get("ALLOWED_EMAIL_DOMAINS", "nurexone.com")).split(",") if d.strip()]
CLAUDE_MODEL = get("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = get("CLAUDE_EFFORT", "high")
EMBED_MODEL = get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RERANK_MODEL = get("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
# Where the embedding/re-ranking models are downloaded; on a server, put it on the
# persistent disk so they are not re-downloaded on every deploy. None = fastembed default.
MODEL_CACHE_DIR = get("MODEL_CACHE_DIR")
# Drive folders to skip entirely (with everything inside), as comma-separated
# name patterns, case-insensitive; * matches anything. E.g. "FlowJo*, Software, Old*".
EXCLUDE_FOLDERS = [p.strip() for p in str(get("EXCLUDE_FOLDERS", "FlowJo*")).split(",") if p.strip()]
# Last API credit top-up, so the sidebar can estimate what's left: amount in USD and
# the date it was added (YYYY-MM-DD). Leave unset to show only this month's spend.
CREDIT_ADDED_USD = float(get("CREDIT_ADDED_USD") or 0) or None
CREDIT_ADDED_ON = get("CREDIT_ADDED_ON")
# Indexed papers that no signed-in user has seen in Drive for this long are removed.
PRUNE_AFTER_DAYS = int(get("PRUNE_AFTER_DAYS", 60))
