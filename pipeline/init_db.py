"""
Initialises the SEO agent SQLite database.
One database, multiple clients, dated snapshots per client.
Safe to re-run: uses CREATE TABLE IF NOT EXISTS.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seo_agent.db")

SCHEMA = """
-- One row per client
CREATE TABLE IF NOT EXISTS clients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    domain          TEXT NOT NULL,
    ga4_property_id TEXT,
    gsc_site_url    TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    active          INTEGER DEFAULT 1
);

-- One row per audit run, per client (a dated snapshot)
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id     INTEGER NOT NULL,
    run_date      TEXT DEFAULT (datetime('now')),
    status        TEXT DEFAULT 'pending',   -- pending | running | complete | failed
    notes         TEXT,
    FOREIGN KEY (client_id) REFERENCES clients(id)
);

-- Technical crawl issues (from LibreCrawl), linked to a snapshot
CREATE TABLE IF NOT EXISTS crawl_issues (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id  INTEGER NOT NULL,
    url          TEXT,
    issue        TEXT,
    issue_type   TEXT,      -- error | warning | notice
    category     TEXT,
    details      TEXT,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

-- GA4 traffic metrics, linked to a snapshot
CREATE TABLE IF NOT EXISTS ga4_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER NOT NULL,
    metric_name     TEXT,      -- e.g. sessions, totalUsers, organic_sessions
    metric_value    REAL,
    dimension       TEXT,      -- optional breakdown (channel, page, etc.)
    period_start    TEXT,
    period_end      TEXT,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

-- GSC search performance, linked to a snapshot
CREATE TABLE IF NOT EXISTS gsc_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   INTEGER NOT NULL,
    query         TEXT,
    page          TEXT,
    clicks        INTEGER,
    impressions   INTEGER,
    ctr           REAL,
    position      REAL,
    period_start  TEXT,
    period_end    TEXT,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

-- Keyword rankings (from DataForSEO), linked to a snapshot
CREATE TABLE IF NOT EXISTS rankings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   INTEGER NOT NULL,
    keyword       TEXT,
    position      INTEGER,
    search_volume INTEGER,
    url           TEXT,
    location      TEXT,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

-- Indexes for fast trend queries (compare snapshots per client)
CREATE INDEX IF NOT EXISTS idx_snapshots_client ON snapshots(client_id, run_date);
CREATE INDEX IF NOT EXISTS idx_crawl_snapshot   ON crawl_issues(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_ga4_snapshot     ON ga4_metrics(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_gsc_snapshot     ON gsc_metrics(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_rankings_snapshot ON rankings(snapshot_id);
"""

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    # Report what exists
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    conn.close()
    print(f"Database ready at: {DB_PATH}")
    print("Tables:", ", ".join(t[0] for t in tables))

if __name__ == "__main__":
    main()
