import { useEffect } from 'react';

import {
  presetRequiresOpportunityState,
  queryRequiresOpportunityState,
  sanitizeQueryForOpportunityCapability,
} from '../opportunityCapabilityPolicy';

export function useOpportunityCapabilityTransition({
  capabilityResolved,
  available,
  query,
  activePreset,
  onSanitizedQuery,
  onUnsupportedPreset,
}) {
  const queryRequiresCapability = queryRequiresOpportunityState(query);
  const presetRequiresCapability = presetRequiresOpportunityState(activePreset);

  useEffect(() => {
    if (!capabilityResolved || available) {
      return;
    }
    if (queryRequiresCapability) {
      onSanitizedQuery(sanitizeQueryForOpportunityCapability(query, false));
    }
    if (presetRequiresCapability) {
      onUnsupportedPreset?.();
    }
  }, [
    activePreset,
    available,
    capabilityResolved,
    onSanitizedQuery,
    onUnsupportedPreset,
    presetRequiresCapability,
    query,
    queryRequiresCapability,
  ]);

  return capabilityResolved && !available && queryRequiresCapability;
}
