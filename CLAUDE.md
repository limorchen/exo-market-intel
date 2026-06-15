# ExoRadar — NurExone Exosome Market & GTM Intelligence Dashboard

Streamlit dashboard for tracking the US commercial exosome market. Covers state-level legislation risk, distributor/KOL/CME/MSO entity tracking, and automated priority scoring — focused exclusively on the commercial (non-IND) pathway.

## Tech Stack

- **Frontend:** Streamlit (Python)
- **Database:** SQLite (`db/exo_market.db`) via `utils/db.py`
- **Deployment:** Streamlit Community Cloud — auto-deploys on push to `main`
- **Deployment URL:** https://exo-market-intel-gbqkgsavxw3zptjkopp9ti.streamlit.app/

## Key Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Seed database (run once, or after rm db/exo_market.db to reset)
python pipeline/seed_states.py
python pipeline/seed_entities.py

# Run locally (WSL2 requires poll watcher)
streamlit run app.py --server.fileWatcherType poll

# Push to deploy (Streamlit Cloud auto-deploys on push)
git push origin main
```

## Project Structure

```
app.py                  # Streamlit entry point
data/
  entities.py           # Seed data — all entity records
  states_seed.csv       # Seed data — state legislation records
db/
  schema.sql            # SQLite schema
  exo_market.db         # Auto-created SQLite database
pipeline/
  seed_states.py        # Load states_seed.csv → state_registry
  seed_entities.py      # Load entities.py → entity_registry
  refresh.py            # Incremental refresh pipeline
utils/
  db.py                 # DB connection, init_db(), _migrate_db()
  scoring.py            # Priority score calculation
```

## Database Schema

Three tables: `state_registry`, `entity_registry`, `update_log`. See `db/schema.sql`.

Key fields on `entity_registry`:
- `name` — UNIQUE constraint (prevents duplicate seeds)
- `ind_seeking` — if 1, entity is excluded from active dashboard (scored 0)
- `active` — 0/1 flag derived from ind_seeking
- `products` — what the entity makes, distributes, or represents
- `recent_deal` — confirmed acquisitions/partnerships (2024–2026); highlighted in UI with 🔥
- `manual_override_score` — bypasses calculated score when set

## Priority Scoring (1–10)

| Factor | Weight | Values |
|---|---|---|
| Legislation risk | 35% | low=10, medium=6, high=3, unknown=1 |
| Geographic reach | 25% | multi-state=10, single large=7, single small=4 |
| Exosome engagement | 25% | active=10, interested=7, adjacent=4, unknown=2 |
| Contact completeness | 15% | website+contact=10, website only=6, neither=2 |

IND-seeking entities are always scored 0.

## Entity Types

- **distributor** — commercial distributors of exosome products
- **KOL** — key opinion leaders / influential practitioners
- **CME** — continuing medical education providers
- **MSO** — management service organizations

## Entity Curation Rules

- Only entities working with multiple partners (suppliers, distributors, clinics) — not single-vendor exclusives
- Must have verifiable web presence
- Entities using autologous/patient-derived material only → `current_exosome_use: adjacent`
- IND-seeking entities → `ind_seeking: 1`, excluded from dashboard

## Database Migration

`utils/db.py:_migrate_db()` handles adding new columns to existing deployed databases using `ALTER TABLE ... ADD COLUMN` with exception swallowing (idempotent). Run automatically on every `init_db()` call.

## Known Issues / Notes

- WSL2: Streamlit inotify file watching doesn't work — always use `--server.fileWatcherType poll` locally
- Streamlit Cloud reads from GitHub `main` branch — push to deploy
- Resetting the database: `rm db/exo_market.db` then re-run seed scripts
