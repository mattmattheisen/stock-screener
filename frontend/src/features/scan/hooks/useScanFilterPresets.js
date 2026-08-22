import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  canonicalizeExpression,
  stableExpressionKey,
} from '../filterExpressionModel';
import { legacyLiveFiltersToExpression } from '../legacyFilterExpression';
import { isOpportunityStateField } from '../scanFilterFields';

const SAFE_SCAN_SORT = Object.freeze({ sortBy: 'composite_score', sortOrder: 'desc' });

function valueReferencesOpportunityState(value) {
  if (Array.isArray(value)) {
    return value.some(valueReferencesOpportunityState);
  }
  if (!value || typeof value !== 'object') {
    return false;
  }
  if (isOpportunityStateField(value.field)) {
    return true;
  }
  return Object.values(value).some(valueReferencesOpportunityState);
}

function isOpportunityStatePreset(preset) {
  return preset?.name === 'Correction Survivors'
    || preset?.filters?.correctionSurvivor != null
    || isOpportunityStateField(preset?.sort_by)
    || valueReferencesOpportunityState(preset?.filters?.expression);
}

export function expressionReferencesOpportunityState(expression) {
  const groups = [expression?.required, ...(expression?.groups ?? [])];
  return groups.some((group) => (
    group?.conditions?.some((condition) => isOpportunityStateField(condition?.field))
  ));
}

export function queryReferencesOpportunityState(expression, sortBy) {
  return expressionReferencesOpportunityState(expression) || isOpportunityStateField(sortBy);
}

function removeOpportunityStateConditions(expression) {
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

export function useScanFilterPresets({
  presets,
  createPresetAsync,
  updatePresetAsync,
  deletePreset,
  sortBy,
  sortOrder,
  applyQuery,
  expression = null,
  opportunityStateAvailable = false,
  opportunityStateCapabilityResolved = true,
}) {
  const [activePresetId, setActivePresetId] = useState(null);
  const [presetFiltersSnapshot, setPresetFiltersSnapshot] = useState(null);
  const [presetSortSnapshot, setPresetSortSnapshot] = useState(null);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [saveDialogMode, setSaveDialogMode] = useState('save');
  const [saveDialogPresetId, setSaveDialogPresetId] = useState(null);
  const [saveDialogInitialName, setSaveDialogInitialName] = useState('');
  const [saveDialogInitialDescription, setSaveDialogInitialDescription] = useState('');
  const [saveDialogError, setSaveDialogError] = useState(null);

  const currentPresetFilters = useMemo(
    () => ({
      schema_version: 2,
      expression: canonicalizeExpression(expression),
    }),
    [expression],
  );
  const availablePresets = useMemo(
    () => (opportunityStateAvailable
      ? presets
      : presets.filter((preset) => !isOpportunityStatePreset(preset))),
    [opportunityStateAvailable, presets],
  );
  const availableActivePresetId = useMemo(
    () => (availablePresets.some((preset) => preset.id === activePresetId)
      ? activePresetId
      : null),
    [activePresetId, availablePresets],
  );

  const clearActivePreset = useCallback(() => {
    setActivePresetId(null);
    setPresetFiltersSnapshot(null);
    setPresetSortSnapshot(null);
  }, []);

  useEffect(() => {
    if (
      activePresetId != null
      && !availablePresets.some((preset) => preset.id === activePresetId)
    ) {
      clearActivePreset();
    }
  }, [activePresetId, availablePresets, clearActivePreset]);

  useEffect(() => {
    if (opportunityStateAvailable || !opportunityStateCapabilityResolved) {
      return;
    }
    const expressionNeedsCleanup = expressionReferencesOpportunityState(expression);
    const sortNeedsCleanup = isOpportunityStateField(sortBy);
    if (!expressionNeedsCleanup && !sortNeedsCleanup) {
      return;
    }
    applyQuery({
      expression: expressionNeedsCleanup
        ? removeOpportunityStateConditions(expression)
        : canonicalizeExpression(expression),
      sortBy: sortNeedsCleanup ? SAFE_SCAN_SORT.sortBy : sortBy,
      sortOrder: sortNeedsCleanup ? SAFE_SCAN_SORT.sortOrder : sortOrder,
    });
  }, [
    applyQuery,
    expression,
    opportunityStateAvailable,
    opportunityStateCapabilityResolved,
    sortBy,
    sortOrder,
  ]);

  const hasUnsavedChanges = useCallback(() => {
    if (!activePresetId || !presetFiltersSnapshot) {
      return false;
    }
    const filtersChanged = currentPresetFilters.schema_version === 2
      && presetFiltersSnapshot.schema_version === 2
      ? stableExpressionKey(currentPresetFilters.expression)
        !== stableExpressionKey(presetFiltersSnapshot.expression)
      : JSON.stringify(currentPresetFilters) !== JSON.stringify(presetFiltersSnapshot);
    const sortChanged =
      presetSortSnapshot &&
      (sortBy !== presetSortSnapshot.sortBy || sortOrder !== presetSortSnapshot.sortOrder);
    return filtersChanged || sortChanged;
  }, [activePresetId, currentPresetFilters, presetFiltersSnapshot, presetSortSnapshot, sortBy, sortOrder]);

  const handleLoadPreset = useCallback(
    (presetId) => {
      if (!presetId) {
        clearActivePreset();
        return;
      }

      const preset = availablePresets.find((item) => item.id === presetId);
      if (!preset) {
        return;
      }

      const isExpressionPreset = preset.filters?.schema_version === 2 && preset.filters?.expression;
      const nextExpression = isExpressionPreset
        ? preset.filters.expression
        : legacyLiveFiltersToExpression(preset.filters);
      applyQuery({
        expression: nextExpression,
        sortBy: preset.sort_by,
        sortOrder: preset.sort_order,
      });
      setActivePresetId(presetId);
      setPresetFiltersSnapshot(
        {
          schema_version: 2,
          expression: canonicalizeExpression(nextExpression),
        },
      );
      setPresetSortSnapshot({ sortBy: preset.sort_by, sortOrder: preset.sort_order });
    },
    [applyQuery, availablePresets, clearActivePreset]
  );

  const handleOpenSaveDialog = useCallback(() => {
    setSaveDialogMode('save');
    setSaveDialogPresetId(null);
    setSaveDialogInitialName('');
    setSaveDialogInitialDescription('');
    setSaveDialogError(null);
    setSaveDialogOpen(true);
  }, []);

  const handleUpdatePreset = useCallback(async () => {
    if (!activePresetId) {
      return;
    }
    try {
      await updatePresetAsync({
        presetId: activePresetId,
        updates: {
          filters: currentPresetFilters,
          sort_by: sortBy,
          sort_order: sortOrder,
        },
      });
      setPresetFiltersSnapshot(currentPresetFilters);
      setPresetSortSnapshot({ sortBy, sortOrder });
    } catch (error) {
      console.error('Failed to update preset:', error);
      alert('Failed to update preset. Please try again.');
    }
  }, [activePresetId, currentPresetFilters, sortBy, sortOrder, updatePresetAsync]);

  const handleRenamePreset = useCallback(
    (presetId) => {
      const preset = availablePresets.find((item) => item.id === presetId);
      if (!preset) {
        return;
      }
      setSaveDialogMode('rename');
      setSaveDialogPresetId(presetId);
      setSaveDialogInitialName(preset.name);
      setSaveDialogInitialDescription(preset.description || '');
      setSaveDialogError(null);
      setSaveDialogOpen(true);
    },
    [availablePresets]
  );

  const handleDeletePreset = useCallback(
    (presetId) => {
      deletePreset(presetId);
      if (activePresetId === presetId) {
        clearActivePreset();
      }
    },
    [activePresetId, clearActivePreset, deletePreset]
  );

  const handleSaveDialogClose = useCallback(() => {
    setSaveDialogOpen(false);
    setSaveDialogError(null);
    setSaveDialogPresetId(null);
  }, []);

  const handleSaveDialogSave = useCallback(
    async (name, description) => {
      setSaveDialogError(null);

      try {
        if (saveDialogMode === 'save') {
          const newPreset = await createPresetAsync({
            name,
            description: description || null,
            filters: currentPresetFilters,
            sort_by: sortBy,
            sort_order: sortOrder,
          });
          setActivePresetId(newPreset.id);
          setPresetFiltersSnapshot(currentPresetFilters);
          setPresetSortSnapshot({ sortBy, sortOrder });
        } else {
          const targetPresetId = saveDialogPresetId ?? activePresetId;
          if (!targetPresetId) {
            setSaveDialogError('No preset selected for rename');
            return;
          }
          await updatePresetAsync({
            presetId: targetPresetId,
            updates: { name, description: description || null },
          });
        }

        setSaveDialogOpen(false);
      } catch (error) {
        console.error('Failed to save preset:', error);
        const errorMessage = error.response?.data?.detail || 'Failed to save preset';
        setSaveDialogError(errorMessage);
      }
    },
    [
      activePresetId,
      createPresetAsync,
      currentPresetFilters,
      saveDialogMode,
      saveDialogPresetId,
      sortBy,
      sortOrder,
      updatePresetAsync,
    ]
  );

  return {
    availablePresets,
    activePresetId: availableActivePresetId,
    hasUnsavedChanges,
    clearActivePreset,
    handleLoadPreset,
    handleOpenSaveDialog,
    handleUpdatePreset,
    handleRenamePreset,
    handleDeletePreset,
    saveDialogOpen,
    saveDialogMode,
    saveDialogInitialName,
    saveDialogInitialDescription,
    saveDialogError,
    handleSaveDialogClose,
    handleSaveDialogSave,
  };
}
