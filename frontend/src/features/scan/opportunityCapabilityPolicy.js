import { canonicalizeExpression } from './filterExpressionModel';
import { legacyLiveFiltersToExpression } from './legacyFilterExpression';
import { isOpportunityStateField } from './scanFilterFields';

export const SAFE_SCAN_SORT = Object.freeze({
  sortBy: 'composite_score',
  sortOrder: 'desc',
});

export function resolveLiveOpportunityCapability(resultsData) {
  return {
    available: resultsData?.capabilities?.opportunity_state === true,
    resolved: resultsData != null,
  };
}

export function resolveStaticOpportunityCapability(marketEntry) {
  return marketEntry.features?.opportunity_state === true;
}

function expressionRequiresOpportunityState(expression) {
  const canonical = canonicalizeExpression(expression);
  return [canonical.required, ...canonical.groups].some((group) => (
    group.conditions.some((condition) => isOpportunityStateField(condition.field))
  ));
}

export function queryRequiresOpportunityState(query) {
  return expressionRequiresOpportunityState(query?.expression)
    || isOpportunityStateField(query?.sortBy ?? query?.sort_by);
}

function presetExpression(preset) {
  if (preset?.filter_expression) {
    return preset.filter_expression;
  }
  if (preset?.filters?.schema_version === 2 && preset.filters.expression) {
    return preset.filters.expression;
  }
  return legacyLiveFiltersToExpression(preset?.filters);
}

export function presetRequiresOpportunityState(preset) {
  return queryRequiresOpportunityState({
    expression: presetExpression(preset),
    sortBy: preset?.sort_by ?? preset?.sortBy,
  });
}

export function filterPresetsForOpportunityCapability(
  presets,
  capabilityResolved,
  available,
) {
  if (!capabilityResolved || available) {
    return presets;
  }
  return presets.filter((preset) => !presetRequiresOpportunityState(preset));
}

function sanitizeExpression(expression) {
  const canonical = canonicalizeExpression(expression);
  const sanitizeGroup = (group) => ({
    ...group,
    conditions: group.conditions.filter(
      (condition) => !isOpportunityStateField(condition.field),
    ),
  });
  return {
    ...canonical,
    required: sanitizeGroup(canonical.required),
    groups: canonical.groups.flatMap((group) => {
      const sanitized = sanitizeGroup(group);
      return group.conditions.length === 0 || sanitized.conditions.length > 0
        ? [sanitized]
        : [];
    }),
  };
}

export function sanitizeQueryForOpportunityCapability(query, available) {
  const normalized = {
    expression: canonicalizeExpression(query?.expression),
    sortBy: query?.sortBy ?? query?.sort_by ?? SAFE_SCAN_SORT.sortBy,
    sortOrder: query?.sortOrder ?? query?.sort_order ?? SAFE_SCAN_SORT.sortOrder,
  };
  if (available) {
    return normalized;
  }
  if (!isOpportunityStateField(normalized.sortBy)) {
    return {
      ...normalized,
      expression: sanitizeExpression(normalized.expression),
    };
  }
  return {
    expression: sanitizeExpression(normalized.expression),
    ...SAFE_SCAN_SORT,
  };
}
