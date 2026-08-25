import { Box, Paper, Typography } from '@mui/material';

import BreadthMetricTooltip from './BreadthMetricTooltip';
import { breadthMetricDefinitions } from './breadthMetricDefinitions';


const contextMetrics = [
  'advancing_count',
  'declining_count',
  'new_high_52week_count',
  'new_low_52week_count',
  't2108_pct',
  'atr_10x_extension_count',
  'broad_universe_count',
];

const eligibleValue = (row, metric) => {
  const eligibleField = breadthMetricDefinitions[metric].eligibleField;
  return eligibleField ? row?.[eligibleField] : null;
};

const formatContextValue = (row, metric) => {
  if (!row) return '—';
  if (metric === 'broad_universe_count') {
    return row[metric] ?? '—';
  }
  const eligible = eligibleValue(row, metric);
  if (!eligible) return '—';
  if (metric === 'advancing_count' || metric === 'declining_count') {
    const count = row[metric] ?? 0;
    return `${count} (${((count / eligible) * 100).toFixed(1)}%)`;
  }
  if (metric === 't2108_pct') {
    const count = row.t2108_count ?? 0;
    const percentage = row.t2108_pct ?? (count / eligible) * 100;
    return `${Number(percentage).toFixed(2)}% (${count} / ${eligible})`;
  }
  return `${row[metric] ?? 0} / ${eligible}`;
};

function BreadthContextStrip({ row }) {
  return (
    <Box
      aria-label="Breadth context"
      sx={{
        display: 'grid',
        gridTemplateColumns: {
          xs: 'repeat(2, minmax(0, 1fr))',
          sm: 'repeat(4, minmax(0, 1fr))',
          lg: 'repeat(7, minmax(0, 1fr))',
        },
        gap: 1,
      }}
    >
      {contextMetrics.map((metric) => (
        <Paper
          key={metric}
          variant="outlined"
          data-testid={`breadth-context-${metric}`}
          sx={{ p: 1, minWidth: 0 }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ fontSize: 10, fontWeight: 700 }}
            >
              {breadthMetricDefinitions[metric].label}
            </Typography>
            <BreadthMetricTooltip metric={metric} compact />
          </Box>
          <Typography
            sx={{ mt: 0.25, fontFamily: 'monospace', fontSize: 13, fontWeight: 700 }}
          >
            {formatContextValue(row, metric)}
          </Typography>
        </Paper>
      ))}
    </Box>
  );
}

export default BreadthContextStrip;
