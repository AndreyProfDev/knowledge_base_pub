import type { QueryClient } from '@tanstack/react-query';
import { act, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { listQueryKey } from '@/lib/list-query';

import { fakeApi, kinds } from './fake-api';
import { renderRoute } from './render-route';

const KINDS = { 'GET /kinds': () => Response.json(kinds) };
const base = { total: 4, done: 4, failed: 0, pending: 0, unchanged: 0, finished: true, failures_truncated: false };
const finished = (run_id: string) => ({ ...base, run_id, failures: [] });

function countInvalidations(queryClient: QueryClient) {
  const listHash = queryClient.getQueryCache().build(queryClient, { queryKey: listQueryKey('knowledge') }).queryHash;
  const count = { value: 0 };
  queryClient.getQueryCache().subscribe((event) => {
    if (event.type === 'updated' && event.action.type === 'invalidate' && event.query.queryHash === listHash) {
      count.value += 1;
    }
  });
  return count;
}

describe('warm-up completion', () => {
  it("invalidates the kinds' lists once, however often the page renders after", async () => {
    const api = fakeApi({
      ...KINDS,
      'GET /warmup/r1': () => Response.json(finished('r1')),
      'POST /warmup': () => new Promise<Response>(() => undefined),
    });
    const { queryClient, user } = await renderRoute('/admin?run=r1', api);
    const invalidations = countInvalidations(queryClient);

    await screen.findByText('4 of 4 written · 0 failed · 0 unchanged');
    await waitFor(() => {
      expect(invalidations.value).toBe(1);
    });
    // A new run's validation phase re-renders the page while the old run is still `finished`.
    queryClient.setQueryData(listQueryKey('knowledge'), { pages: [], pageParams: [] });
    await user.click(screen.getByRole('button', { name: 'Run warm-up' }));
    await screen.findByRole('button', { name: 'Validating files…' });
    await act(() => Promise.resolve());

    expect(invalidations.value).toBe(1);
  });

  it('invalidates once for each finished run, across a new run started from the page', async () => {
    const api = fakeApi({
      ...KINDS,
      'GET /warmup/r1': () => Response.json(finished('r1')),
      'GET /warmup/r2': () => Response.json(finished('r2')),
      'POST /warmup': () => Response.json({ run_id: 'r2', kinds: {}, total_queued: 4, shadowed: [] }),
    });
    const { queryClient, user } = await renderRoute('/admin?run=r1', api);
    const invalidations = countInvalidations(queryClient);
    await screen.findByText('4 of 4 written · 0 failed · 0 unchanged');
    await waitFor(() => {
      expect(invalidations.value).toBe(1);
    });
    // `invalidate` dispatches only on a query not already invalidated.
    queryClient.setQueryData(listQueryKey('knowledge'), { pages: [], pageParams: [] });
    await user.click(screen.getByRole('button', { name: 'Run warm-up' }));
    await screen.findByText('4 queued');
    await waitFor(() => {
      expect(invalidations.value).toBe(2);
    });
  });
});

describe('the per-kind table', () => {
  it('belongs to the run just started, not to another run in the URL', async () => {
    const report = { run_id: 'r1', kinds: { knowledge: { queued: 4, unchanged: 0 } }, total_queued: 4, shadowed: [] };
    const api = fakeApi({
      ...KINDS,
      'GET /warmup/r1': () => Response.json(finished('r1')),
      'GET /warmup/r2': () => Response.json(finished('r2')),
      'POST /warmup': () => Response.json(report),
    });
    const { user, router } = await renderRoute('/admin', api);
    await user.click(screen.getByRole('button', { name: 'Run warm-up' }));
    await screen.findByText('4 queued');

    await act(() => router.navigate({ to: '/admin', search: { run: 'r2' } }));

    await waitFor(() => {
      expect(screen.queryByText('4 queued')).toBeNull();
    });
  });

  it('lists each hand-written copy a differing dump copy shadowed', async () => {
    const shadow = { hand_written: 'a.yaml:knowledge[0]', dump: 'knowledge-k1.yaml:knowledge[0]' };
    const report = { run_id: 'r1', kinds: {}, total_queued: 1, shadowed: [shadow] };
    const api = fakeApi({
      ...KINDS,
      'GET /warmup/r1': () => Response.json(finished('r1')),
      'POST /warmup': () => Response.json(report),
    });
    const { user } = await renderRoute('/admin', api);
    await user.click(screen.getByRole('button', { name: 'Run warm-up' }));

    expect(await screen.findByText(/differ from their dump copies/)).toBeTruthy();
    expect(screen.getByText(shadow.hand_written)).toBeTruthy();
    expect(screen.getByText(shadow.dump)).toBeTruthy();
  });
});

describe('failed writes', () => {
  const failure = { request_id: 'q1', item_id: 'i-q1', kind: 'knowledge', error: 'boom' };

  it('are not listed while the run is still writing', async () => {
    const running = { ...finished('r1'), done: 1, failed: 1, pending: 2, finished: false, failures: [failure] };
    await renderRoute('/admin?run=r1', fakeApi({ ...KINDS, 'GET /warmup/r1': () => Response.json(running) }));

    await screen.findByText('2 of 4 written · 1 failed · 0 unchanged');

    expect(screen.queryByText('Failed writes')).toBeNull();
  });

  it('say "and more" only when the list is truncated', async () => {
    const done = { ...finished('r1'), done: 3, failed: 1, failures: [failure] };
    await renderRoute('/admin?run=r1', fakeApi({ ...KINDS, 'GET /warmup/r1': () => Response.json(done) }));

    await screen.findByText('Failed writes');

    expect(screen.queryByText('and more')).toBeNull();
  });
});
