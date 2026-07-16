-- Phase 1 sanity queries. Real data only, so numbers are small but should be
-- sensible. Each statement is preceded by a `-- label` line that run_sanity.py
-- uses as a heading. Portable SQL (no CLI dot-commands), so it also runs under
-- the duckdb CLI:  duckdb analytics/data/analytics.duckdb < sanity_queries.sql

-- Q1: launches by sector (curated real-world sectors)
SELECT c.sector, COUNT(*) AS launches
FROM launches l JOIN companies c USING (company_id)
GROUP BY c.sector
ORDER BY launches DESC, c.sector;

-- Q2: launches by company (top 10)
SELECT c.ticker, c.name, COUNT(*) AS launches
FROM launches l JOIN companies c USING (company_id)
GROUP BY c.ticker, c.name
ORDER BY launches DESC, c.ticker
LIMIT 10;

-- Q3: avg 1-year and (synthetic) 1-day stock change by sector
SELECT c.sector,
       ROUND(AVG(s.change_1y), 2) AS avg_change_1y_pct,
       ROUND(AVG(s.change_1d), 2) AS avg_change_1d_pct
FROM stock_snapshots s JOIN companies c USING (company_id)
GROUP BY c.sector
ORDER BY avg_change_1y_pct DESC;

-- Q4: synthesized launch categories
SELECT category, COUNT(*) AS launches
FROM launches
GROUP BY category
ORDER BY launches DESC, category;

-- Q5: confirmation signal - source-type mix, avg sources, avg derived confidence
SELECT source_type,
       COUNT(*)                        AS launches,
       ROUND(AVG(num_sources), 2)      AS avg_sources,
       ROUND(AVG(confidence_score), 2) AS avg_confidence
FROM launches
GROUP BY source_type
ORDER BY launches DESC;

-- Integrity: row counts per table
SELECT 'companies' AS tbl, COUNT(*) AS n FROM companies
UNION ALL SELECT 'launches', COUNT(*) FROM launches
UNION ALL SELECT 'sources', COUNT(*) FROM sources
UNION ALL SELECT 'stock_snapshots', COUNT(*) FROM stock_snapshots
UNION ALL SELECT 'feedback', COUNT(*) FROM feedback;

-- Integrity: orphaned foreign keys (expect all zeros)
SELECT
  (SELECT COUNT(*) FROM launches l        WHERE l.company_id NOT IN (SELECT company_id FROM companies)) AS orphan_launches,
  (SELECT COUNT(*) FROM sources s         WHERE s.launch_id  NOT IN (SELECT launch_id  FROM launches))  AS orphan_sources,
  (SELECT COUNT(*) FROM stock_snapshots x WHERE x.launch_id  NOT IN (SELECT launch_id  FROM launches))  AS orphan_snapshots;
