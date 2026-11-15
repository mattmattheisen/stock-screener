-- READ ONLY: audit the existing stock_prices table before any backfill.
-- Running these queries does NOT fix or certify price data.
-- Compare results with an independently retrieved, licensed corporate-action
-- and historical adjusted-price source before approving any correction.

-- A. Inventory of adjusted-price anomalies by symbol.
SELECT
    symbol,
    COUNT(*) AS row_count,
    COUNT(*) FILTER (WHERE adj_close IS NULL) AS missing_adjusted,
    COUNT(*) FILTER (
        WHERE adj_close IS NOT NULL AND adj_close <= 0
    ) AS invalid_adjusted,
    COUNT(*) FILTER (
        WHERE adj_close IS NOT NULL AND close IS NOT NULL
          AND ABS(adj_close - close) < 0.000001
    ) AS equal_raw_adjusted_requires_verification,
    MIN(date) AS first_session,
    MAX(date) AS last_session
FROM stock_prices
GROUP BY symbol
ORDER BY missing_adjusted DESC, equal_raw_adjusted_requires_verification DESC, symbol;

-- B. Focused CAN SLIM universe; list rows needing independent reconciliation.
-- Equality is NOT proof of corruption, especially when factor legitimately 1.
SELECT symbol, date, open, high, low, close, adj_close, volume
FROM stock_prices
WHERE symbol IN ('MSFT', 'TSM', 'ANET', 'LLY', 'FTNT')
  AND (
    adj_close IS NULL OR adj_close <= 0 OR close IS NULL
    OR ABS(COALESCE(adj_close, 0) - COALESCE(close, 0)) < 0.000001
  )
ORDER BY symbol, date;

-- C. Potentially discontinuous daily raw closes; NOT synonymous with splits.
WITH bars AS (
    SELECT symbol, date, close,
           LAG(close) OVER (PARTITION BY symbol ORDER BY date) AS previous_close
    FROM stock_prices
    WHERE symbol IN ('MSFT', 'TSM', 'ANET', 'LLY', 'FTNT')
)
SELECT symbol, date, previous_close, close,
       (close / NULLIF(previous_close, 0) - 1) AS raw_day_change
FROM bars
WHERE previous_close > 0
  AND ABS(close / NULLIF(previous_close, 0) - 1) > 0.35
ORDER BY symbol, date;

-- D. Duplicate natural keys (DB constraint should make this zero).
SELECT symbol, date, COUNT(*) AS count_rows
FROM stock_prices
GROUP BY symbol, date
HAVING COUNT(*) > 1;
