# Market-calibrated breadth revision 3

Market breadth now uses fixed, rounded StockBee eligibility thresholds expressed in each supported market's primary trading currency. The shared live, backfill, attribution, and static calculation layer no longer depends on historical FX; broad context indicators remain available when a listing's currency differs from the market policy, while only its StockBee eligibility is excluded.

Existing installations must run the revision-3 shadow rebuild and atomic activation for all breadth-enabled markets. Revision-2 rows and static fallbacks are intentionally not served after the new code is deployed, so breadth can be temporarily unavailable until activation and dependent exposure/snapshot/static rebuilds finish. No database schema migration is required.

AU, SG, and MY remain breadth-disabled. Their bootstrap, daily, snapshot, and static workflows now skip breadth and breadth-derived exposure instead of treating those absent sections as failures.
