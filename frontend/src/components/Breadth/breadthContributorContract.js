export const BREADTH_CONTRIBUTOR_SCHEMA = 'breadth-contributors-v1';
export const BREADTH_CONTRIBUTOR_REVISION = 3;
export const BREADTH_CONTRIBUTOR_RETENTION = 20;

const normalizeMarket = (market) => String(market || '').trim().toUpperCase();

export const validateBreadthContributorIndex = (index, expectedMarket) => {
  const dates = index?.dates;
  if (
    index?.schema !== BREADTH_CONTRIBUTOR_SCHEMA
    || index?.calculation_revision !== BREADTH_CONTRIBUTOR_REVISION
    || normalizeMarket(index?.market) !== normalizeMarket(expectedMarket)
    || !Array.isArray(dates)
    || dates.length > BREADTH_CONTRIBUTOR_RETENTION
    || new Set(dates).size !== dates.length
    || dates.some((date) => !/^\d{4}-\d{2}-\d{2}$/.test(date))
    || dates.some((date, position) => position > 0 && dates[position - 1] < date)
  ) {
    throw new Error('Invalid breadth contributor index');
  }
  return index;
};

export const validateBreadthContributorDocumentIdentity = (
  document,
  { market, date } = {},
) => {
  if (document?.schema !== BREADTH_CONTRIBUTOR_SCHEMA) {
    throw new Error('Unsupported breadth contributor schema');
  }
  if (document?.calculation_revision !== BREADTH_CONTRIBUTOR_REVISION) {
    throw new Error('Unsupported breadth contributor revision');
  }
  if (
    (market && normalizeMarket(document?.market) !== normalizeMarket(market))
    || (date && document?.date !== date)
  ) {
    throw new Error('Breadth contributor document identity does not match the request');
  }
  return document;
};
