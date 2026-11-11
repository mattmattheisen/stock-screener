# Unusual Whales historical price retrieval

The connected Unusual Whales **ChatGPT app** has been verified for daily
ticker OHLC history (ANET: 300 observations, 2025-09-04 through 2026-11-11).
That connection is not a credential that can be transferred to GitHub Codespaces.

The public Unusual Whales REST documentation also describes
`GET /api/stock/{ticker}/ohlc/1d`. The two interfaces may have different
schemas and entitlements; **do not assume they are identical**.

A research-only REST probe is available:

```bash
# Only if you already have an authorized Unusual Whales REST API token:
export UW_API_KEY='your-token'  # enter locally; never share or commit it
python -m research.canslim_adaptive_entry_study.uw_rest_probe \
  --ticker ANET --limit 300 --output /tmp/uw_anet_raw.json
```

The script requests one ticker, archives the unmodified JSON, and prints
only schema field names, record count and SHA-256. It never writes to
PostgreSQL or production. It does **not** print credentials.

If the endpoint does not provide share volume, split adjustment metadata,
or a point-in-time security identifier, the dataset is not full-backtest-ready.
The separately tested `unusual_whales_adapter.py` works with ChatGPT MCP
day-state records and explicitly marks share volume unavailable. It is
not automatically applied to the REST endpoint.

The next step after a successful probe is to inspect the returned schema
and create an explicit REST-to-archive mapping, with adjustment and volume
verification. Do not silently map options contract volume to stock shares.

Sources:
- https://unusualwhales.com/public-api
- https://unusualwhales.com/public-api/examples/get-all-flow-alerts

Do not buy an additional API subscription without first confirming your
existing Unusual Whales plan includes REST API access.
