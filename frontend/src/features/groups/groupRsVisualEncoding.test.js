import { describe, expect, it } from 'vitest';

import { formatGroupRs } from './groupRankingFields';
import { groupRsTone } from './groupRsVisualEncoding';

describe('groupRsTone', () => {
  it.each([
    { value: 79.96, formatted: '80.0', tone: 'up-strong' },
    { value: 69.96, formatted: '70.0', tone: 'up-soft' },
    { value: 30.04, formatted: '30.0', tone: 'down-soft' },
    { value: 20.04, formatted: '20.0', tone: 'down-strong' },
  ])(
    'classifies $value from its displayed value $formatted',
    ({ value, formatted, tone }) => {
      expect(formatGroupRs(value)).toBe(formatted);
      expect(groupRsTone(value)).toBe(tone);
    },
  );
});
