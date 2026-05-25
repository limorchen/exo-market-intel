"""Stub for scheduled pipeline refresh. Run manually or via cron."""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.db import get_conn, init_db

if __name__ == "__main__":
    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO update_log (log_date, change_type, description, logged_by) VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), "refresh", "Manual refresh triggered", "pipeline"),
        )
    print(f"[{datetime.now(timezone.utc).isoformat()}] Refresh stub ran. No remote sources configured yet.")
