# NurExone — Exosome US Market Intelligence Dashboard

A Streamlit dashboard for tracking the US commercial exosome market. Covers state-level legislation risk, distributor/KOL/CME/MSO entity tracking, and automated priority scoring — focused exclusively on the commercial (non-IND) pathway.

## Features

- **Legislation Map** — choropleth of all 50 states color-coded by regulatory risk (low / medium / high / unknown), with a filterable detail table
- **Entity Registry** — filterable, sortable table of distributors, KOLs, CME providers, and MSOs with priority scores; click-to-expand entity profiles and Excel export
- **Priority Scoring** — automatic 1–10 score per entity based on state legislation risk, geographic reach, exosome engagement level, and contact completeness
- **Update Log** — auditable change history for all entity additions and pipeline runs
- **Add Entity form** — add entities directly from the sidebar; IND-seeking entities are automatically excluded and scored 0
- **Refresh Pipeline** — one-click pipeline trigger from the sidebar

## Project Structure

```
app.py                  # Streamlit dashboard (entry point)
requirements.txt
data/
  entities.py           # Seed data for entity_registry
  states_seed.csv       # Seed data for state_registry (state legislation)
db/
  schema.sql            # SQLite schema (state_registry, entity_registry, update_log)
  exo_market.db         # SQLite database (auto-created on first run)
pipeline/
  seed_states.py        # Load states_seed.csv → state_registry
  seed_entities.py      # Load entities.py → entity_registry
  refresh.py            # Incremental refresh pipeline
utils/
  db.py                 # DB connection helpers, schema init
  scoring.py            # Priority score calculation
```

## Setup

```bash
pip install -r requirements.txt
```

## Database Initialization

Run the seed scripts once before launching the dashboard:

```bash
python pipeline/seed_states.py
python pipeline/seed_entities.py
```

## Running

```bash
streamlit run app.py
```

## Priority Scoring

Scores are calculated on a 1–10 scale as a weighted composite:

| Factor | Weight | Description |
|---|---|---|
| Legislation risk | 35% | Risk level of entity's state(s) — low=10, medium=6, high=3 |
| Geographic reach | 25% | Multi-state=10, single large state=7, single small state=4 |
| Exosome engagement | 25% | active=10, interested=7, adjacent=4, unknown=2 |
| Contact completeness | 15% | Website + contact=10, website only=6, neither=2 |

IND-seeking entities are automatically scored 0 and excluded from the active dashboard.

## Entity Types

- **distributor** — commercial distributors of exosome products
- **KOL** — key opinion leaders
- **CME** — continuing medical education providers
- **MSO** — management service organizations
