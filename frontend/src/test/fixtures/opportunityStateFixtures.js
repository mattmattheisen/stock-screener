const AS_OF_DATE = '2026-08-21';

const ALL_CHECKS = [
  'required_evidence',
  'leadership_gate',
  'trend_gate',
  'structure_gate',
  'liquidity_gate',
  'freshness_gate',
];

const availableEvidence = (overrides = {}) => ({
  required_evidence: 'complete',
  benchmark: 'available',
  invalidation: 'available',
  setup: 'available',
  liquidity: 'available',
  event_calendar: 'available',
  prior_run: 'not_requested',
  ...overrides,
});

const metrics = ({
  rsRating1m = 90,
  rsRating3m = 80,
  hardInvalidation = false,
} = {}) => ({
  benchmark_relative_return_65d: 0.08,
  rs_rating_1m: rsRating1m,
  rs_rating_3m: rsRating3m,
  rs_line_new_high: true,
  rs_line_blue_dot: false,
  stage: 2,
  ma_alignment: true,
  hard_invalidation: hardInvalidation,
  pattern_primary: 'vcp',
  squeeze: true,
  tight_closes_count: 3,
  quiet_days_count: 3,
  volume_vs_50d: 0.7,
  volume_dry_up_max: 0.8,
  liquidity_passes: true,
  feature_status: 'complete',
  is_scannable: true,
});

const evidence = ({
  benchmarkAsOfDate = AS_OF_DATE,
  passedChecks = ALL_CHECKS,
  failedChecks = [],
  warnings = [],
  scorePillars,
  rowMetrics,
  dataAvailability = availableEvidence(),
  actionReasons,
}) => ({
  schema_version: 1,
  policy_version: 'correction-survivors-v1',
  as_of_date: AS_OF_DATE,
  market: 'US',
  mic: 'XNAS',
  benchmark_symbol: 'SPY',
  benchmark_as_of_date: benchmarkAsOfDate,
  passed_checks: [...passedChecks],
  failed_checks: [...failedChecks],
  warnings: [...warnings],
  score_pillars: { ...scorePillars },
  metrics: { ...rowMetrics },
  data_availability: { ...dataAvailability },
  action_reasons: [...actionReasons],
});

const pillars = ({ multiHorizon = 17, trendIntegrity = 20 } = {}) => ({
  benchmark_leadership: 20,
  multi_horizon_rs: multiHorizon,
  trend_integrity: trendIntegrity,
  structure_tightness: 20,
  liquidity_freshness: 20,
});

const scanRow = ({
  symbol,
  index,
  correctionSurvivor,
  resilienceScore,
  actionState,
  opportunityState,
}) => ({
  symbol,
  company_name: `${symbol[0]}${symbol.slice(1).toLowerCase()} Fixture`,
  composite_score: 90 - index,
  rating: symbol === 'LEGACY' ? 'Watch' : 'Strong Buy',
  correction_survivor: correctionSurvivor,
  resilience_score: resilienceScore,
  action_state: actionState,
  opportunity_state: opportunityState,
  current_price: 100 + index,
  volume: 150_000_000 + index,
  market_cap_usd: 2_000_000_000 + index,
  market: 'US',
  exchange: 'NASDAQ',
  currency: 'USD',
  screeners_run: symbol === 'LEGACY' ? ['minervini'] : ['minervini', 'setup_engine'],
  price_sparkline_data: null,
  rs_sparkline_data: null,
});

export const OPPORTUNITY_STATE_ROWS = [
  scanRow({
    symbol: 'EXIT',
    index: 0,
    correctionSurvivor: false,
    resilienceScore: 93,
    actionState: 'exit_risk',
    opportunityState: evidence({
      passedChecks: ALL_CHECKS.filter((check) => check !== 'trend_gate'),
      failedChecks: ['trend_gate'],
      scorePillars: pillars({ trendIntegrity: 16 }),
      rowMetrics: metrics({ hardInvalidation: true }),
      actionReasons: ['hard_invalidation:breaks_50d_support'],
    }),
  }),
  scanRow({
    symbol: 'DETERIORATING',
    index: 1,
    correctionSurvivor: true,
    resilienceScore: 95,
    actionState: 'deteriorating',
    opportunityState: evidence({
      scorePillars: pillars({ multiHorizon: 15 }),
      rowMetrics: metrics({ rsRating1m: 80, rsRating3m: 70 }),
      dataAvailability: availableEvidence({ prior_run: 'available' }),
      actionReasons: ['deterioration_confirmed'],
    }),
  }),
  scanRow({
    symbol: 'EVENT',
    index: 2,
    correctionSurvivor: true,
    resilienceScore: 96.6,
    actionState: 'event_risk',
    opportunityState: evidence({
      benchmarkAsOfDate: '2026-08-20',
      warnings: ['benchmark_date_lag'],
      scorePillars: pillars({ multiHorizon: 16.6 }),
      rowMetrics: metrics({ rsRating1m: 88, rsRating3m: 78 }),
      actionReasons: ['earnings_soon'],
    }),
  }),
  scanRow({
    symbol: 'EXTENDED',
    index: 3,
    correctionSurvivor: true,
    resilienceScore: 95,
    actionState: 'extended',
    opportunityState: evidence({
      scorePillars: pillars({ multiHorizon: 15 }),
      rowMetrics: metrics({ rsRating1m: 80, rsRating3m: 70 }),
      actionReasons: ['extended'],
    }),
  }),
  scanRow({
    symbol: 'LIMITED',
    index: 4,
    correctionSurvivor: false,
    resilienceScore: 97,
    actionState: 'data_limited',
    opportunityState: evidence({
      passedChecks: ALL_CHECKS.filter((check) => check !== 'required_evidence'),
      failedChecks: ['required_evidence'],
      scorePillars: pillars(),
      rowMetrics: metrics(),
      dataAvailability: availableEvidence({
        required_evidence: 'incomplete',
        event_calendar: 'unavailable',
      }),
      actionReasons: ['required_evidence'],
    }),
  }),
  scanRow({
    symbol: 'READY',
    index: 5,
    correctionSurvivor: true,
    resilienceScore: 97,
    actionState: 'setup_ready',
    opportunityState: evidence({
      scorePillars: pillars(),
      rowMetrics: metrics(),
      actionReasons: ['setup_ready'],
    }),
  }),
  scanRow({
    symbol: 'WATCH',
    index: 6,
    correctionSurvivor: true,
    resilienceScore: 95,
    actionState: 'watch',
    opportunityState: evidence({
      scorePillars: pillars({ multiHorizon: 15 }),
      rowMetrics: metrics({ rsRating1m: 80, rsRating3m: 70 }),
      actionReasons: ['watch'],
    }),
  }),
  scanRow({
    symbol: 'LEGACY',
    index: 40,
    correctionSurvivor: null,
    resilienceScore: null,
    actionState: null,
    opportunityState: null,
  }),
];

export const ALL_SYMBOLS = OPPORTUNITY_STATE_ROWS.map((row) => row.symbol);

export const CORRECTION_SURVIVORS_SCREEN = {
  id: 'correction_survivors',
  name: 'Correction Survivors',
  short_name: 'Survivors',
  description: 'Leaders that held trend and relative-strength evidence through a correction',
  tier: 1,
  filters: { correctionSurvivor: true },
  sort_by: 'resilience_score',
  sort_order: 'desc',
  filter_schema_version: 2,
  filter_expression: {
    expression_version: 1,
    required: {
      id: 'required',
      name: 'Always require',
      match: 'all',
      enabled: true,
      conditions: [{
        kind: 'boolean',
        field: 'correction_survivor',
        value: true,
      }],
    },
    group_join: 'any',
    groups: [],
  },
};

export const STATIC_SCAN_MANIFEST = {
  schema_version: 'static-scan-v2',
  features: { opportunity_state: true },
  generated_at: '2026-08-21T22:00:00Z',
  as_of_date: AS_OF_DATE,
  run_id: 1201,
  sort: { field: 'composite_score', order: 'desc' },
  default_page_size: 50,
  rows_total: OPPORTUNITY_STATE_ROWS.length,
  default_filters: { minVolume: null },
  default_filtered_rows_total: OPPORTUNITY_STATE_ROWS.length,
  filter_options: { ibd_industries: [], gics_sectors: [], ratings: ['Strong Buy', 'Watch'] },
  preset_screens: [CORRECTION_SURVIVORS_SCREEN],
  chunks: [],
  initial_rows: OPPORTUNITY_STATE_ROWS,
  preview_rows: OPPORTUNITY_STATE_ROWS,
  charts: { available: false },
};

export const STATIC_HOME_PAYLOAD = {
  schema_version: 'static-site-v3',
  generated_at: '2026-08-21T22:00:00Z',
  as_of_date: AS_OF_DATE,
  market: 'US',
  market_display_name: 'United States',
  freshness: {
    scan_as_of_date: AS_OF_DATE,
    scan_published_at: '2026-08-21T22:00:00Z',
  },
  key_markets: [],
  market_health_exposure: {
    date: AS_OF_DATE,
    stance: 'Confirmed Uptrend',
    benchmark_symbol: 'SPY',
  },
  scan_summary: {
    run_id: 1201,
    rows_total: OPPORTUNITY_STATE_ROWS.length,
    default_filtered_rows_total: OPPORTUNITY_STATE_ROWS.length,
    top_results: OPPORTUNITY_STATE_ROWS,
  },
  top_groups: [],
};

export const buildStaticRootManifest = (capability) => {
  const features = { scan: true };
  if (capability !== undefined) {
    features.opportunity_state = capability;
  }
  return {
    schema_version: 'static-site-v3',
    generated_at: '2026-08-21T22:00:00Z',
    as_of_date: AS_OF_DATE,
    default_market: 'US',
    supported_markets: ['US'],
    features,
    markets: {
      US: {
        display_name: 'United States',
        as_of_date: AS_OF_DATE,
        features,
        pages: {
          home: { path: 'markets/us/home.json' },
          scan: { path: 'markets/us/scan/manifest.json' },
        },
        assets: {},
      },
    },
  };
};
