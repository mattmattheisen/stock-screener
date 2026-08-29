import { breadthMetricDefinitions } from './breadthMetricDefinitions';
import {
  BREADTH_CONTRIBUTOR_SCHEMA,
  validateBreadthContributorDocumentIdentity,
} from './breadthContributorContract';

const NO_GROUP = 'No Group';

const finiteNumber = (value, label, { nullable = false } = {}) => {
  if (nullable && value == null) return null;
  const number = Number(value);
  if (!Number.isFinite(number)) throw new Error(`${label} must be finite`);
  return number;
};

export const buildBreadthContributorView = (
  document,
  metricKey,
  expectedCount,
  expectedIdentity,
) => {
  validateBreadthContributorDocumentIdentity(document, expectedIdentity);
  const definition = breadthMetricDefinitions[metricKey];
  if (!definition?.contributor) throw new Error(`${metricKey} does not support contributors`);
  if (!Array.isArray(document.contributors)) throw new Error('Breadth contributors must be an array');

  const { signalKey, direction } = definition.contributor;
  const symbols = new Set();
  const stocks = document.contributors.flatMap((item) => {
    const symbol = String(item?.symbol || '').trim();
    if (!symbol || symbols.has(symbol)) throw new Error('Breadth contributor symbols must be unique');
    symbols.add(symbol);
    if (!Object.prototype.hasOwnProperty.call(item?.signals || {}, signalKey)) return [];
    const qualifyingValue = finiteNumber(item.signals[signalKey], 'Qualifying value');
    const dailyChangePct = finiteNumber(item.daily_change_pct, '1-day change', { nullable: true });
    return [{
      symbol,
      companyName: item.company_name || null,
      groupName: String(item.ibd_industry_group || '').trim() || NO_GROUP,
      qualifyingValue,
      dailyChangePct,
    }];
  });

  if (stocks.length !== Number(expectedCount)) {
    throw new Error('Contributor count does not match breadth history');
  }
  const multiplier = direction === 'down' ? 1 : -1;
  stocks.sort((left, right) => (
    multiplier * (left.qualifyingValue - right.qualifyingValue)
    || left.symbol.localeCompare(right.symbol)
  ));

  const grouped = new Map();
  stocks.forEach((stock) => {
    const members = grouped.get(stock.groupName) || [];
    members.push(stock);
    grouped.set(stock.groupName, members);
  });
  const groups = [...grouped.entries()].map(([name, members]) => ({
    name,
    count: members.length,
    sharePct: stocks.length ? (members.length / stocks.length) * 100 : 0,
    stocks: members,
  }));
  groups.sort((left, right) => {
    if (left.name === NO_GROUP) return 1;
    if (right.name === NO_GROUP) return -1;
    return right.count - left.count || left.name.localeCompare(right.name);
  });

  return {
    schema: BREADTH_CONTRIBUTOR_SCHEMA,
    market: document.market,
    date: document.date,
    metricKey,
    definition,
    count: stocks.length,
    stocks,
    groups,
  };
};
