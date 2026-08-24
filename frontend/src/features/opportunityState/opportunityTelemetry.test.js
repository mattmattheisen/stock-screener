import { beforeEach, describe, expect, it, vi } from 'vitest';

import apiClient from '../../api/client';
import { recordOpportunityEvidenceOpen } from './opportunityTelemetry';

vi.mock('../../api/client', () => ({
  default: {
    post: vi.fn(),
  },
}));

describe('recordOpportunityEvidenceOpen', () => {
  beforeEach(() => {
    apiClient.post.mockReset();
  });

  it.each(['scan', 'daily', 'watchlist'])(
    'sends only market and allowed %s surface',
    async (surface) => {
      apiClient.post.mockResolvedValue({ status: 204 });

      await expect(recordOpportunityEvidenceOpen('US', surface)).resolves.toBeUndefined();

      expect(apiClient.post).toHaveBeenCalledOnce();
      expect(apiClient.post).toHaveBeenCalledWith(
        '/v1/telemetry/opportunity/evidence-open',
        { market: 'US', surface },
      );
      expect(Object.keys(apiClient.post.mock.calls[0][1]).sort()).toEqual(['market', 'surface']);
      expect(JSON.stringify(apiClient.post.mock.calls[0][1]).toLowerCase()).not.toContain('symbol');
    },
  );

  it('swallows network failure', async () => {
    apiClient.post.mockRejectedValue(new Error('offline'));

    await expect(recordOpportunityEvidenceOpen('US', 'scan')).resolves.toBeUndefined();
  });

  it('does not send an unknown surface', async () => {
    await expect(recordOpportunityEvidenceOpen('US', 'other')).resolves.toBeUndefined();

    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
