import { useEffect, useRef } from 'react';
import {
  Box,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { recordOpportunityEvidenceOpen } from '../../features/opportunityState/opportunityTelemetry';
import ActionStateBadge from './ActionStateBadge';

const NOT_AVAILABLE = 'Not available';

const PILLARS = Object.freeze([
  ['benchmark_leadership', 'Benchmark leadership'],
  ['multi_horizon_rs', 'Multi-horizon RS'],
  ['trend_integrity', 'Trend integrity'],
  ['structure_tightness', 'Structure/tightness'],
  ['liquidity_freshness', 'Liquidity/freshness'],
]);

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

const formatValue = (value) => {
  if (value === null || value === undefined || value === '') return NOT_AVAILABLE;
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

const formatScore = (score) => {
  if (score === null || score === undefined || score === '') return NOT_AVAILABLE;
  const numericScore = Number(score);
  return Number.isFinite(numericScore) ? numericScore.toFixed(1) : String(score);
};

const formatCode = (value) => {
  const words = String(value).replace(/[_-]/g, ' ');
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
};

function Section({ title, children }) {
  return (
    <Box component="section" sx={{ mb: 2.5 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.75 }}>
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function Detail({ label, value }) {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, py: 0.35 }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography variant="body2" sx={{ textAlign: 'right' }}>{formatValue(value)}</Typography>
    </Box>
  );
}

function EvidenceList({ values, formatItem = formatCode }) {
  if (!Array.isArray(values) || values.length === 0) {
    return <Typography variant="body2" color="text.secondary">{NOT_AVAILABLE}</Typography>;
  }

  return (
    <List dense disablePadding>
      {values.map((value, index) => (
        <ListItem key={`${String(value)}-${index}`} disableGutters sx={{ py: 0.15 }}>
          <ListItemText primary={formatItem(value)} primaryTypographyProps={{ variant: 'body2' }} />
        </ListItem>
      ))}
    </List>
  );
}

function EvidenceDetails({ values, formatValues = false }) {
  if (!isRecord(values) || Object.keys(values).length === 0) {
    return <Typography variant="body2" color="text.secondary">{NOT_AVAILABLE}</Typography>;
  }

  return Object.entries(values).map(([key, value]) => (
    <Detail
      key={key}
      label={formatCode(key)}
      value={formatValues && typeof value === 'string' ? formatCode(value) : value}
    />
  ));
}

function OpportunityEvidenceDrawer({
  open,
  row,
  onClose,
  onEvidenceOpen,
  opportunityTelemetrySurface,
}) {
  const wasOpen = useRef(false);
  const hasRow = isRecord(row);
  const isOpen = Boolean(open && hasRow);

  useEffect(() => {
    if (isOpen && !wasOpen.current) {
      onEvidenceOpen?.(row);
      if (opportunityTelemetrySurface) {
        const evidence = isRecord(row.opportunity_state) ? row.opportunity_state : {};
        void recordOpportunityEvidenceOpen(evidence.market, opportunityTelemetrySurface);
      }
    }
    wasOpen.current = isOpen;
  }, [isOpen, onEvidenceOpen, opportunityTelemetrySurface, row]);

  if (!hasRow) return null;

  const evidence = isRecord(row.opportunity_state) ? row.opportunity_state : {};
  const scorePillars = isRecord(evidence.score_pillars)
    ? evidence.score_pillars
    : {};

  return (
    <Drawer
      anchor="right"
      open={isOpen}
      onClose={onClose}
      PaperProps={{ sx: { width: { xs: '100%', sm: 420 }, p: 2 } }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 2 }}>
        <Typography id="opportunity-evidence-title" component="h2" variant="h6">
          Opportunity evidence
        </Typography>
        <IconButton aria-label="Close opportunity evidence" onClick={onClose} size="small">
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      <Section title="Action state">
        <ActionStateBadge state={row.action_state} />
      </Section>

      <Section title="Resilience score">
        <Typography variant="h4" component="p">{formatScore(row.resilience_score)}</Typography>
      </Section>

      <Section title="Score pillars">
        {PILLARS.map(([key, label]) => <Detail key={key} label={label} value={scorePillars[key]} />)}
      </Section>

      <Section title="Data availability">
        <EvidenceDetails values={evidence.data_availability} formatValues />
      </Section>

      <Section title="Metrics">
        <EvidenceDetails values={evidence.metrics} />
      </Section>

      <Section title="Passed checks">
        <EvidenceList values={evidence.passed_checks} />
      </Section>

      <Section title="Failed checks">
        <EvidenceList values={evidence.failed_checks} />
      </Section>

      <Section title="Warnings">
        <EvidenceList values={evidence.warnings} />
      </Section>

      <Section title="Action reasons">
        <EvidenceList values={evidence.action_reasons} formatItem={(reason) => String(reason)} />
      </Section>

      <Section title="Provenance">
        <Detail label="Market" value={evidence.market} />
        <Detail label="MIC" value={evidence.mic} />
        <Detail label="Benchmark" value={evidence.benchmark_symbol} />
        <Detail label="As-of date" value={evidence.as_of_date} />
        <Detail label="Benchmark date" value={evidence.benchmark_as_of_date} />
      </Section>
    </Drawer>
  );
}

export { OpportunityEvidenceDrawer };
export default OpportunityEvidenceDrawer;
