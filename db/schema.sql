CREATE TABLE IF NOT EXISTS state_registry (
    state_code TEXT PRIMARY KEY,
    state_name TEXT NOT NULL,
    legislation_type TEXT,
    key_provisions TEXT,
    effective_date TEXT,
    physician_admin_allowed INTEGER DEFAULT 0,
    wellness_allowed INTEGER DEFAULT 0,
    aesthetics_allowed INTEGER DEFAULT 0,
    risk_level TEXT,
    notes TEXT,
    source_url TEXT,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS entity_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    states TEXT,
    country TEXT DEFAULT 'US',
    us_reach INTEGER DEFAULT 1,
    specialty TEXT,
    current_exosome_use TEXT,
    ind_seeking INTEGER DEFAULT 0,
    website TEXT,
    contact_info TEXT,
    linkedin_url TEXT,
    priority_score REAL,
    manual_override_score REAL,
    products TEXT,
    recent_deal TEXT,
    notes TEXT,
    source TEXT,
    last_updated TEXT,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS update_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER,
    log_date TEXT,
    change_type TEXT,
    description TEXT,
    source_url TEXT,
    logged_by TEXT DEFAULT 'pipeline'
);
