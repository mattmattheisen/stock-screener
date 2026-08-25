import {
  Box,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material';
import { format } from 'date-fns';

import BreadthMetricTooltip from './BreadthMetricTooltip';
import {
  breadthMetricDefinitions,
  primaryBreadthMetrics,
  secondaryBreadthMetrics,
  tableContextMetrics,
} from './breadthMetricDefinitions';


const upMetrics = new Set([
  'stocks_up_4pct',
  'stocks_up_25pct_quarter',
  'stocks_up_25pct_month',
  'stocks_up_50pct_month',
  'stocks_up_13pct_34days',
]);
const downMetrics = new Set([
  'stocks_down_4pct',
  'stocks_down_25pct_quarter',
  'stocks_down_25pct_month',
  'stocks_down_50pct_month',
  'stocks_down_13pct_34days',
]);

const formatValue = (row, metric) => {
  const value = row?.[metric];
  if (value == null) return '—';
  if (metric === 'ratio_5day' || metric === 'ratio_10day') {
    return Number(value).toFixed(2);
  }
  if (metric === 't2108_pct') return `${Number(value).toFixed(2)}%`;
  return value;
};

const metricCellSx = (metric) => ({
  fontFamily: 'monospace',
  fontWeight: upMetrics.has(metric) || downMetrics.has(metric) ? 700 : 500,
  color: upMetrics.has(metric)
    ? 'success.main'
    : downMetrics.has(metric)
      ? 'error.main'
      : 'text.primary',
  backgroundColor: upMetrics.has(metric)
    ? 'rgba(46, 125, 50, 0.08)'
    : downMetrics.has(metric)
      ? 'rgba(211, 47, 47, 0.08)'
      : 'transparent',
  whiteSpace: 'nowrap',
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
          {rows.slice(0, maxRows).map((row) => (
            <TableRow key={row.date} hover>
              <TableCell
                sx={{
                  position: 'sticky',
                  left: 0,
                  zIndex: 2,
                  bgcolor: 'background.paper',
                  fontFamily: 'monospace',
                  whiteSpace: 'nowrap',
                }}
              >
                {format(new Date(row.date), 'MM/dd/yy')}
              </TableCell>
              {metrics.map((metric) => (
                <TableCell
                  key={metric}
                  align="right"
                  data-testid={
                    upMetrics.has(metric)
                      ? 'breadth-up-cell'
                      : downMetrics.has(metric)
                        ? 'breadth-down-cell'
                        : undefined
                  }
                  sx={metricCellSx(metric)}
                >
                  {formatValue(row, metric)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

export default BreadthHistoryTable;
