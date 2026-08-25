import {
  Box,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material';
import { format, parseISO } from 'date-fns';
import { useMemo } from 'react';

import BreadthMetricTooltip from './BreadthMetricTooltip';
import {
  breadthMetricDefinitions,
  primaryBreadthMetrics,
  secondaryBreadthMetrics,
  tableContextMetrics,
} from './breadthMetricDefinitions';
import {
  BREADTH_VISUAL_COLORS,
  buildDirectionalToneThresholds,
  isDirectionalMetric,
  metricTone,
} from './breadthVisualEncoding';

const formatValue = (row, metric) => {
  const value = row?.[metric];
  if (value == null) return '—';
  const eligibleField = breadthMetricDefinitions[metric]?.eligibleField;
  const eligibleValue = eligibleField ? row?.[eligibleField] : null;
  if (eligibleValue != null && Number(eligibleValue) <= 0) return '—';
  if (metric === 'ratio_5day' || metric === 'ratio_10day') {
    return Number(value).toFixed(2);
  }
  if (metric === 't2108_pct') return `${Number(value).toFixed(2)}%`;
  return value;
};

const metricCellSx = (metric, tone) => ({
  fontFamily: 'monospace',
  fontWeight: isDirectionalMetric(metric) ? 700 : 500,
  color: '#fff',
  backgroundColor: BREADTH_VISUAL_COLORS[tone],
  borderColor: 'rgba(255, 255, 255, 0.06)',
  whiteSpace: 'nowrap',
  transition: 'background-color 120ms ease',
});

function MetricHeader({ metric }) {
  return (
    <TableCell align="right" sx={{ whiteSpace: 'nowrap', fontSize: 11 }}>
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
        {breadthMetricDefinitions[metric].label}
        <BreadthMetricTooltip metric={metric} compact />
      </Box>
    </TableCell>
  );
}

function BreadthHistoryTable({ rows = [], maxRows = 90 }) {
  const metrics = [
    ...primaryBreadthMetrics,
    ...secondaryBreadthMetrics,
    ...tableContextMetrics,
  ];
  const visibleRows = useMemo(() => rows.slice(0, maxRows), [maxRows, rows]);
  const toneThresholds = useMemo(
    () => buildDirectionalToneThresholds(visibleRows),
    [visibleRows],
  );
  return (
    <TableContainer
      data-testid="breadth-history-scroll"
      sx={{ overflowX: 'auto', maxHeight: 'calc(100vh - 360px)' }}
    >
      <Table stickyHeader size="small" sx={{ minWidth: 1660 }}>
        <TableHead>
          <TableRow>
            <TableCell
              rowSpan={2}
              sx={{ position: 'sticky', left: 0, zIndex: 5, fontWeight: 700 }}
            >
              Date
            </TableCell>
            <TableCell align="center" colSpan={primaryBreadthMetrics.length}>
              Primary Breadth Indicators
            </TableCell>
            <TableCell align="center" colSpan={secondaryBreadthMetrics.length}>
              Secondary Breadth Indicators
            </TableCell>
            <TableCell align="center" colSpan={tableContextMetrics.length}>
              Context
            </TableCell>
          </TableRow>
          <TableRow>
            {metrics.map((metric) => <MetricHeader key={metric} metric={metric} />)}
          </TableRow>
        </TableHead>
        <TableBody>
          {visibleRows.map((row) => (
            <TableRow key={row.date} hover>
              <TableCell
                sx={{
                  position: 'sticky',
                  left: 0,
                  zIndex: 2,
                  bgcolor: BREADTH_VISUAL_COLORS.neutral,
                  color: '#fff',
                  fontFamily: 'monospace',
                  fontWeight: 600,
                  whiteSpace: 'nowrap',
                }}
              >
                {format(parseISO(row.date), 'MM/dd/yy')}
              </TableCell>
              {metrics.map((metric) => {
                const tone = metricTone(row, metric, toneThresholds);
                return (
                  <TableCell
                    key={metric}
                    align="right"
                    data-testid={`breadth-cell-${metric}`}
                    data-tone={tone}
                    sx={metricCellSx(metric, tone)}
                  >
                    {formatValue(row, metric)}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

export default BreadthHistoryTable;
