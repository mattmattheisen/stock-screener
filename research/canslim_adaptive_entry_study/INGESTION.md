# Historical OHLCV ingestion prototype

This is a **research-only** importer for provider-exported daily OHLCV. It is deliberately
standard-library-only, so it runs in a Codespace with Python 3.14 without installing
the stock screener's backend dependencies. It does not access PostgreSQL or production.

CSV required columns:

```csv
symbol,date,open,high,low,close,volume,adjustment_basis,source
XYZ,2024-01-02,10,11,9,10.5,1000,split_adjusted,research_export
```

Permitted `adjustment_basis`: `split_adjusted`, `raw_as_traded`,
`total_return_adjusted`. The provider must establish this basis; do not
guess. For the price-breakout study, **split-adjusted OHLC** is preferred;
dividend-adjusted total-return bars must not be silently mixed with them.

From the repository root:

```bash
python -m research.canslim_adaptive_entry_study.ohlcv_archive \
  --input /path/to/provider_export.csv \
  --output /tmp/canslim_ohlcv_normalized.csv \
  --manifest /tmp/canslim_ohlcv_manifest.json
```

The output contains chronological per-symbol bars and a SHA-256 manifest.
Existing output files are never overwritten. The importer rejects duplicate
symbol/dates, missing values, invalid OHLC relationships, and invalid volume.

**Not yet provided:** a licensed historical source, a survivorship-free symbol
universe, corporate-action reconstruction, earnings and institutional data
available-at timestamps, or historical proprietary IBD RS. Consequently this
archive is not a complete CAN SLIM backtest dataset and must not generate
live orders or performance claims.

Yahoo/yfinance can export daily prices with explicit `auto_adjust` and
`actions` options, but it is only a provisional research source; verify
split/dividend semantics, provider terms, delisted coverage and revisions
before using it. See official documentation:
https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
