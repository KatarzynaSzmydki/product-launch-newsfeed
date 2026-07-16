-- Analytics star schema (Phase 1).
--
-- Seeded from the live product-launch-newsfeed output — REAL rows only (no
-- synthetic backfill). Every row is a real launch/company/snapshot. Columns the
-- app has no source for are filled at the attribute level: company sector/etc.
-- from a curated real-world map (company_attrs.csv), launches.category
-- synthesized, launches.confidence_score a heuristic over real signals, and
-- stock_snapshots.change_1d synthesized. See analytics/PROJECT_PLAN.md section 8.
--
-- Executed top-to-bottom by generate_data.py, so DROP in reverse-FK order.

DROP TABLE IF EXISTS feedback;
DROP TABLE IF EXISTS stock_snapshots;
DROP TABLE IF EXISTS sources;
DROP TABLE IF EXISTS launches;
DROP TABLE IF EXISTS companies;

CREATE TABLE companies (
    company_id        INTEGER PRIMARY KEY,
    ticker            VARCHAR NOT NULL UNIQUE,
    name              VARCHAR NOT NULL,
    sector            VARCHAR,   -- curated real-world value (company_attrs.csv)
    industry          VARCHAR,   -- curated real-world value (company_attrs.csv)
    hq_country        VARCHAR,   -- curated real-world value (company_attrs.csv)
    market_cap_bucket VARCHAR    -- curated real-world value (company_attrs.csv)
);

CREATE TABLE launches (
    launch_id        INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES companies(company_id),
    launch_date      DATE,
    keyword          VARCHAR,   -- matched launch verb (real)
    product_name     VARCHAR,   -- only in summary prose; not extracted (NULL)
    category         VARCHAR,   -- synthesized, sector-correlated
    confidence_score DOUBLE,    -- heuristic over num_sources + tier (real signals)
    num_sources      INTEGER,   -- derived from trigger events (real)
    source_type      VARCHAR,   -- 'wire' | 'multi_outlet' (derived, real)
    summary          VARCHAR,   -- brief Launch Summary prose (real)
    is_synthetic     BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE sources (
    source_id    INTEGER PRIMARY KEY,
    launch_id    INTEGER NOT NULL REFERENCES launches(launch_id),
    outlet_name  VARCHAR,
    url          VARCHAR,
    published_at DATE,          -- proxy: run detected_at, not true publish time
    is_wire      BOOLEAN        -- tier-1 wire hit (real)
);

CREATE TABLE stock_snapshots (
    snapshot_id   INTEGER PRIMARY KEY,
    company_id    INTEGER NOT NULL REFERENCES companies(company_id),
    launch_id     INTEGER REFERENCES launches(launch_id),
    snapshot_date DATE,
    price         DOUBLE,       -- current price at brief time (real)
    change_1d     DOUBLE,       -- synthesized (app captures no intraday change)
    change_1y     DOUBLE,       -- 1-year % change (real)
    week52_high   DOUBLE,       -- real
    week52_low    DOUBLE        -- real
);

-- Part of the section-8 star schema, left empty under "real data only": real
-- feedback lives in GitHub Issues and needs a network call to ingest.
CREATE TABLE feedback (
    feedback_id   INTEGER PRIMARY KEY,
    submitted_at  TIMESTAMP,
    feedback_type VARCHAR,
    status        VARCHAR,
    launch_id     INTEGER REFERENCES launches(launch_id)
);

-- The operational query_log table (semantic cache + eval harness) is deferred to
-- Phase 5/8, where it's designed against the actual cache — the DB is gitignored
-- and rebuilt from scratch each run, so there's no migration to pre-empt.
