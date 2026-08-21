import { useMemo, useState } from 'react';
import { Box, Chip, Paper, Typography } from '@mui/material';

import { ACTION_STATE_META } from '../../features/opportunityState/actionState';
import DailyScanRowsTable from './DailyScanRowsTable';
import OpportunityEvidenceDrawer from './OpportunityEvidenceDrawer';

const EMPTY_ROWS = [];

function CorrectionSurvivorsPanel({
  summary,
  posture,
  chartEnabledSymbols = null,
  navigationSymbols,
  onOpenChart = null,
  opportunityTelemetrySurface,
}) {
  const [opportunityRow, setOpportunityRow] = useState(null);
  const isComplete = summary?.available === true && summary?.complete === true;
  const rows = isComplete && Array.isArray(summary?.rows) ? summary.rows : EMPTY_ROWS;
  const rowSymbols = useMemo(
    () => rows.map((row) => row?.symbol).filter(Boolean),
    [rows],
  );
  const resolvedNavigationSymbols = navigationSymbols ?? rowSymbols;

  return (
    <Paper
      data-testid="correction-survivors-panel"
      component="section"
      elevation={0}
      sx={{ p: 1.5, mb: 2, border: '1px solid', borderColor: 'divider' }}
    >
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 2,
          flexWrap: 'wrap',
          mb: 1,
        }}
      >
        <Box>
          <Typography
            component="h2"
            variant="subtitle1"
            sx={{ fontWeight: 600, fontSize: '13px', textTransform: 'uppercase', letterSpacing: '0.5px' }}
          >
            Correction Survivors
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {posture?.stance || 'Market posture unavailable'}
          </Typography>
        </Box>
        {posture ? (
          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
            {posture.date || 'Date unavailable'} · {posture.benchmark_symbol || 'Benchmark unavailable'}
          </Typography>
        ) : null}
      </Box>

      {!isComplete ? (
        <Typography role="status" variant="body2" color="warning.main" sx={{ py: 1 }}>
          Survivor data incomplete
        </Typography>
      ) : (
        <>
          <Typography variant="body2" sx={{ fontWeight: 700, mb: 1 }}>
            Total survivors: {summary.count}
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mb: 1.5 }}>
            {Object.entries(ACTION_STATE_META).map(([state, meta]) => (
              <Chip
                key={state}
                label={`${meta.label}: ${summary.counts_by_action_state?.[state] ?? 0}`}
                color={meta.color}
                size="small"
                variant="outlined"
              />
            ))}
          </Box>
          <DailyScanRowsTable
            title="Top Resilience"
            subtitle="Top 20 rows in the persisted survivor ranking. Select an action state for evidence."
            rows={rows}
            chartEnabledSymbols={chartEnabledSymbols}
            navigationSymbols={resolvedNavigationSymbols}
            onOpenChart={onOpenChart}
            emptyMessage="No correction survivors in this snapshot."
            scoreField="resilience_score"
            showActionState
            onOpenOpportunity={setOpportunityRow}
          />
        </>
      )}

      <OpportunityEvidenceDrawer
        open={Boolean(opportunityRow)}
        row={opportunityRow}
        onClose={() => setOpportunityRow(null)}
        opportunityTelemetrySurface={opportunityTelemetrySurface}
      />
    </Paper>
  );
}

export { CorrectionSurvivorsPanel };
export default CorrectionSurvivorsPanel;
