import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Collapse,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  Tooltip,
  Typography,
  useMediaQuery,
} from '@mui/material';
import { useTheme } from '@mui/material/styles';
import CloseIcon from '@mui/icons-material/Close';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import { breadthMetricDefinitions } from './breadthMetricDefinitions';

const formatValue = (value, valueKind) => {
  if (value == null) return '—';
  if (valueKind === 'multiple') return `${Number(value).toFixed(2)}x`;
  return `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(2)}%`;
};

const StockRows = ({ stocks, valueKind }) => stocks.map((stock) => (
  <TableRow key={stock.symbol}>
    <TableCell sx={{ fontWeight: 700, color: 'primary.light' }}>{stock.symbol}</TableCell>
    <TableCell sx={{ maxWidth: 190 }}>
      <Tooltip title={stock.companyName || ''}>
        <Typography noWrap variant="body2">{stock.companyName || '—'}</Typography>
      </Tooltip>
    </TableCell>
    <TableCell sx={{ maxWidth: 180 }}>
      <Tooltip title={stock.groupName}>
        <Typography noWrap variant="body2">{stock.groupName}</Typography>
      </Tooltip>
    </TableCell>
    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums', fontWeight: 700 }}>
      {formatValue(stock.qualifyingValue, valueKind)}
    </TableCell>
    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
      {formatValue(stock.dailyChangePct, 'percent')}
    </TableCell>
  </TableRow>
));

const StockTable = ({ stocks, definition }) => (
  <TableContainer sx={{ maxHeight: { xs: 'calc(100vh - 190px)', sm: 520 } }}>
    <Table stickyHeader size="small" aria-label="Breadth contributing stocks">
      <TableHead>
        <TableRow>
          <TableCell>Ticker</TableCell>
          <TableCell>Company</TableCell>
          <TableCell>IBD Group</TableCell>
          <TableCell align="right" aria-label={`Qualifying value: ${definition.contributor.qualifierLabel}`}>
            <Tooltip title={definition.contributor.qualifierLabel}>
              <span>Qualifying value</span>
            </Tooltip>
          </TableCell>
          <TableCell align="right">1-day change</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        <StockRows stocks={stocks} valueKind={definition.contributor.valueKind} />
      </TableBody>
    </Table>
  </TableContainer>
);

const GroupList = ({ groups, definition }) => {
  const [expanded, setExpanded] = useState(null);
  return (
    <Stack spacing={0.75} sx={{ py: 1 }}>
      {groups.map((group) => {
        const isExpanded = expanded === group.name;
        return (
          <Box key={group.name} sx={{ border: 1, borderColor: 'divider', borderRadius: 1 }}>
            <Button
              fullWidth
              color="inherit"
              aria-expanded={isExpanded}
              aria-label={`${group.name}, ${group.count} stocks, ${group.sharePct.toFixed(1)} percent`}
              onClick={() => setExpanded(isExpanded ? null : group.name)}
              startIcon={isExpanded ? <ExpandMoreIcon /> : <ChevronRightIcon />}
              sx={{ justifyContent: 'flex-start', px: 1.5, py: 1, textTransform: 'none' }}
            >
              <Typography sx={{ flex: 1, textAlign: 'left', fontWeight: 700 }}>{group.name}</Typography>
              <Typography color="text.secondary" variant="body2">
                {group.count} · {group.sharePct.toFixed(1)}%
              </Typography>
            </Button>
            <Collapse in={isExpanded} unmountOnExit>
              <StockTable stocks={group.stocks} definition={definition} />
            </Collapse>
          </Box>
        );
      })}
    </Stack>
  );
};

const BreadthContributorDialog = ({
  open,
  metric,
  row,
  view,
  isLoading = false,
  error = null,
  unavailable = false,
  inconsistent = null,
  onRetry,
  onClose,
}) => {
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'));
  const [tab, setTab] = useState(0);
  const definition = breadthMetricDefinitions[metric] || { label: 'Breadth contributors' };
  const count = Number(row?.[metric] || view?.count || 0);
  const titleId = 'breadth-contributor-dialog-title';
  useEffect(() => {
    if (!open) setTab(0);
  }, [open]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullScreen={fullScreen}
      fullWidth
      maxWidth="md"
      aria-labelledby={titleId}
    >
      <DialogTitle id={titleId} sx={{ pr: 6, pb: 1 }}>
        <Typography component="span" sx={{ fontWeight: 800 }}>
          {definition.label}
        </Typography>
        <Typography component="span" color="text.secondary">
          {` · ${row?.date || ''} · ${count} stocks`}
        </Typography>
        <IconButton aria-label="Close" onClick={onClose} sx={{ position: 'absolute', right: 10, top: 10 }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <Tabs value={tab} onChange={(_event, value) => setTab(value)} sx={{ px: 3, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="Stocks" />
        <Tab label="IBD Groups" />
      </Tabs>
      <DialogContent sx={{ p: { xs: 1.5, sm: 2.5 }, minHeight: 260 }}>
        {isLoading && (
          <Stack alignItems="center" justifyContent="center" spacing={1.5} sx={{ minHeight: 220 }}>
            <CircularProgress size={30} />
            <Typography color="text.secondary">Loading contributors…</Typography>
          </Stack>
        )}
        {!isLoading && inconsistent && <Alert severity="warning">{inconsistent}</Alert>}
        {!isLoading && !inconsistent && unavailable && (
          <Alert severity="info">Contributor details are not available for this session.</Alert>
        )}
        {!isLoading && !inconsistent && !unavailable && error && (
          <Alert
            severity={view ? 'warning' : 'error'}
            action={<Button color="inherit" size="small" onClick={onRetry}>Retry</Button>}
            sx={view ? { mb: 1.5 } : undefined}
          >
            {view ? 'Showing cached contributors because the latest refresh failed.' : 'Could not load contributors.'}
          </Alert>
        )}
        {!isLoading && !inconsistent && !unavailable && view && (
          tab === 0
            ? <StockTable stocks={view.stocks} definition={view.definition} />
            : <GroupList groups={view.groups} definition={view.definition} />
        )}
      </DialogContent>
    </Dialog>
  );
};

export default BreadthContributorDialog;
