import { QueryClient } from '@tanstack/react-query';
import { act, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fakeApi, kinds } from './fake-api';
import { renderRoute } from './render-route';

const base = { failed: 0, unchanged: 0, failures: [], failures_truncated: false };
const running = (run_id: string) => ({ ...base, run_id, total: 4, done: 1, pending: 3, finished: false });
const finished = (run_id: string) => ({ ...base, run_id, total: 4, done: 4, pending: 0, finished: true });
const noRetryDelay = () => new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } });
const button = () => screen.getByRole<HTMLButtonElement>('button', { name: 'Run warm-up' });

afterEach(() => {
  vi.useRealTimers();
});

describe('a stale run', () => {
  it('shows "not known" at once under the default retry, without retrying the 404', async () => {
    const api = fakeApi({ 'GET /kinds': () => Response.json(kinds) });
    await renderRoute('/admin?run=gone', api, new QueryClient());

    await screen.findByText('This warm-up run is not known', {}, { timeout: 500 });

    expect(api.requests.filter((r) => r.url.endsWith('/warmup/gone'))).toHaveLength(1);
    expect(button().disabled).toBe(false);
  });
});

describe('a run forgotten mid-run (404 after data)', () => {
  it('frees the button and drops the stale bar', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    let polls = 0;
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /warmup/r1': () => {
        polls += 1;
        return polls === 1 ? Response.json(running('r1')) : Response.json({ detail: 'gone' }, { status: 404 });
      },
    });
    await renderRoute('/admin?run=r1', api, noRetryDelay());
    await screen.findByText(/^1 of 4 written/);
    await act(() => vi.advanceTimersByTimeAsync(1000));
    await screen.findByText('This warm-up run is not known');
    expect(button().disabled).toBe(false);
    expect(screen.queryByRole('progressbar')).toBeNull();
  });
});

describe('a 5xx before any data', () => {
  it('keeps the button disabled and polls until data arrives', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    let polls = 0;
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /warmup/r1': () => {
        polls += 1;
        return polls <= 4 ? Response.json({ detail: 'down' }, { status: 503 }) : Response.json(finished('r1'));
      },
    });
    await renderRoute('/admin?run=r1', api, noRetryDelay());
    await screen.findByText('Progress unknown: 503 down');
    expect(button().disabled).toBe(true);
    await act(() => vi.advanceTimersByTimeAsync(1000));
    await screen.findByText('4 of 4 written · 0 failed · 0 unchanged');
    expect(screen.queryByText(/Progress unknown/)).toBeNull();
    expect(button().disabled).toBe(false);
  });
});

describe('a failed poll mid-run', () => {
  it('keeps the last data, keeps polling and keeps the button disabled until the run finishes', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    let polls = 0;
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /warmup/r1': () => {
        polls += 1;
        if (polls === 1) return Response.json(running('r1'));
        return polls <= 5 ? Response.json({ detail: 'restarting' }, { status: 502 }) : Response.json(finished('r1'));
      },
    });
    await renderRoute('/admin?run=r1', api, noRetryDelay());

    await screen.findByText(/^1 of 4 written/);
    await act(() => vi.advanceTimersByTimeAsync(1000));
    await screen.findByText('Progress unknown: 502 restarting');
    expect(screen.getByText(/^1 of 4 written/)).toBeTruthy();
    expect(button().disabled).toBe(true);
    await act(() => vi.advanceTimersByTimeAsync(1000));

    await screen.findByText('4 of 4 written · 0 failed · 0 unchanged');
    expect(button().disabled).toBe(false);
  });
});
