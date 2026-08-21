import { postOpportunityEvidenceOpen } from '../../api/telemetry';

const LIVE_OPPORTUNITY_SURFACES = new Set(['scan', 'daily', 'watchlist']);

/** Best-effort client telemetry. Never blocks or fails the evidence drawer. */
export const recordOpportunityEvidenceOpen = async (market, surface) => {
  if (!LIVE_OPPORTUNITY_SURFACES.has(surface)) return;

  try {
    await postOpportunityEvidenceOpen(market, surface);
  } catch {
    // Advisory telemetry must not affect the user workflow.
  }
};
