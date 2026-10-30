import { QueryClient } from '@tanstack/react-query';
import { act, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { WarmupProgress, WarmupReport } from '@/lib/api';
import { listQueryKey } from '@/lib/list-query';

import { type FakeApi, fakeApi, kinds } from './fake-api';
import { renderRoute } from './render-route';

const KINDS = { 'GET /kinds': () => Response.json(kinds) };
const report: WarmupReport = {
  run_id: 'r1',
  kinds: { knowledge: { queued: 3, unchanged: 1 }, entity: { queued: 1, unchanged: 0 } },
  total_queued: 4,
  shadowed: [],
};

function progress(fields: Partial<WarmupProgress>): WarmupProgress {
  const p = {
    run_id: 'r1',
    total: 4,
    done: 0,
    failed: 0,
    unchanged: 1,
    failures: [],
    failures_truncated: false,
    ...fields,
  };
  const pending = p.total - p.done - p.failed;
  return { pending, finished: pending === 0, ...p };
}

// Answers each in turn, then repeats the last.
function answers(...bodies: WarmupProgress[]) {
  const queue = [...bodies];
  return () => Response.json(queue.length > 1 ? queue.shift() : queue[0]);
}

const calls = (api: FakeApi, method: string, path: string) =>
  api.requests.filter((r) => r.method === method && new URL(r.url).pathname === `/api${path}`).length;
const bar = () => screen.getByRole('progressbar', { name: 'Warm-up progress' });
const button = () => screen.getByRole<HTMLButtonElement>('button', { name: /Run warm-up|Validating files…/ });

// Only the poll's interval is faked; testing-library's waits keep real timeouts.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
});
afterEach(() => {
  vi.useRealTimers();
});

describe('admin navigation', () => {
  it('links to /admin from the nav, after Search', async () => {
    await renderRoute('/search', fakeApi(KINDS));

    const links = within(screen.getByRole('navigation')).getAllByRole('link');
    expect(links.map((link) => link.textContent).slice(-2)).toEqual(['Search', 'Admin']);
    expect(links.at(-1)?.getAttribute('href')).toBe('/admin');
  });
});

describe('warm-up run', () => {
  it('posts once, shows the validation phase, then puts the run in the URL', async () => {
    let release = () => undefined as unknown;
    const posted = new Promise<Response>((resolve) => {
      release = () => {
        resolve(Response.json(report));
      };
    });
    const api = fakeApi({ ...KINDS, 'POST /warmup': () => posted, 'GET /warmup/r1': answers(progress({})) });
    const { user, router } = await renderRoute('/admin', api);

    expect(screen.getByText(/configured warm-up directory; unchanged items are skipped/)).toBeTruthy();
    await user.click(button());
    expect(button().textContent).toBe('Validating files…');
    expect(button().disabled).toBe(true);
    release();

    await waitFor(() => {
      expect(router.state.location.search).toEqual({ run: 'r1' });
    });
    expect(calls(api, 'POST', '/warmup')).toBe(1);
    const table = (await screen.findByText('4 queued')).closest('table') as HTMLElement;
    expect(
      within(table)
        .getAllByRole('row')
        .map((row) => row.textContent),
    ).toEqual(['KindQueuedUnchanged', 'knowledge31', 'entity10']);
    await screen.findByText('0 of 4 written · 0 failed · 1 unchanged');
    expect(button().disabled).toBe(true);
  });

  it('follows the run to the end, then stops polling and re-enables the button', async () => {
    const api = fakeApi({
      ...KINDS,
      'GET /warmup/r1': answers(progress({ done: 1 }), progress({ done: 4 })),
    });
    await renderRoute('/admin?run=r1', api);

    await waitFor(() => {
      expect(bar().getAttribute('aria-valuenow')).toBe('25');
    });
    expect(screen.getByText('1 of 4 written · 0 failed · 1 unchanged')).toBeTruthy();
    expect(screen.getByText(/retried for up to ~2.5 minutes/)).toBeTruthy();
    expect(button().disabled).toBe(true);

    await act(() => vi.advanceTimersByTimeAsync(1000));
    await waitFor(() => {
      expect(bar().getAttribute('aria-valuenow')).toBe('100');
    });
    expect(screen.getByText('4 of 4 written · 0 failed · 1 unchanged')).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(5000));

    expect(calls(api, 'GET', '/warmup/r1')).toBe(2);
    expect(calls(api, 'POST', '/warmup')).toBe(0);
    expect(button().disabled).toBe(false);
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('shows a full bar when nothing was queued', async () => {
    await renderRoute(
      '/admin?run=r1',
      fakeApi({ ...KINDS, 'GET /warmup/r1': answers(progress({ total: 0, unchanged: 2 })) }),
    );

    expect(await screen.findByText('Nothing to write: all 2 items unchanged')).toBeTruthy();
    expect(bar().getAttribute('aria-valuenow')).toBe('100');
  });

  it('lists the failed writes, each linking to its request', async () => {
    const failures = ['q1', 'q2'].map((id) => ({
      request_id: id,
      item_id: `i-${id}`,
      kind: 'knowledge',
      error: `boom ${id}`,
    }));
    const body = progress({ done: 2, failed: 2, failures, failures_truncated: true });
    await renderRoute('/admin?run=r1', fakeApi({ ...KINDS, 'GET /warmup/r1': answers(body) }));

    const table = (await screen.findByText('Failed writes')).closest('table') as HTMLElement;
    expect(bar().getAttribute('aria-valuenow')).toBe('100');
    expect(screen.getByText('4 of 4 written · 2 failed · 1 unchanged')).toBeTruthy();
    const links = within(table).getAllByRole('link');
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['i-q1', '/requests/q1'],
      ['i-q2', '/requests/q2'],
    ]);
    expect(within(table).getByText('boom q2')).toBeTruthy();
    expect(screen.getByText('and more')).toBeTruthy();
  });
});

describe('warm-up completion', () => {
  it("invalidates the kinds' lists once the run finishes, not before", async () => {
    const api = fakeApi({
      ...KINDS,
      'GET /warmup/r1': answers(progress({ done: 1 }), progress({ done: 4 })),
    });
    const { queryClient } = await renderRoute('/admin?run=r1', api);
    queryClient.setQueryData(listQueryKey('knowledge'), { pages: [], pageParams: [] });
    const invalidated = () => queryClient.getQueryState(listQueryKey('knowledge'))?.isInvalidated;

    await waitFor(() => {
      expect(bar().getAttribute('aria-valuenow')).toBe('25');
    });
    expect(invalidated()).toBe(false);

    await act(() => vi.advanceTimersByTimeAsync(1000));
    await waitFor(() => {
      expect(invalidated()).toBe(true);
    });
  });
});

describe('warm-up failures', () => {
  it('lists every invalid item of a 422 inline, without a dialog', async () => {
    const detail = [
      { type: 'warmup_item_invalid', loc: ['a.yaml', 'knowledge', 0, 'content'], msg: 'Field required', ctx: {} },
      { type: 'warmup_item_invalid', loc: ['b.yaml', 'recipe'], msg: 'not an installed kind' },
      { type: 'warmup_item_invalid', loc: ['c.yaml'], msg: 'invalid YAML' },
    ];
    const api = fakeApi({ ...KINDS, 'POST /warmup': () => Response.json({ detail }, { status: 422 }) });
    const { user, router } = await renderRoute('/admin', api);

    await user.click(button());

    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('The warm-up files are invalid; nothing was queued.')).toBeTruthy();
    expect(
      within(alert)
        .getAllByRole('row')
        .map((row) => row.textContent),
    ).toEqual([
      'FileKindIndexMessage',
      'a.yamlknowledge0content: Field required',
      'b.yamlrecipenot an installed kind',
      'c.yamlinvalid YAML',
    ]);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(router.state.location.search).toEqual({});
    expect(button().disabled).toBe(false);
  });

  it('names the missing directory of a 404 on POST', async () => {
    const missing = { detail: 'warm-up directory /x does not exist' };
    const api = fakeApi({ ...KINDS, 'POST /warmup': () => Response.json(missing, { status: 404 }) });
    const { user } = await renderRoute('/admin', api);

    await user.click(button());

    expect((await screen.findByRole('alert')).textContent).toBe('warm-up directory /x does not exist');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('toasts any other POST failure', async () => {
    const api = fakeApi({ ...KINDS, 'POST /warmup': () => Response.json({ detail: 'queue down' }, { status: 500 }) });
    const { user } = await renderRoute('/admin', api);

    await user.click(button());

    expect(await screen.findByText('Warm-up failed')).toBeTruthy();
    expect(screen.getByText('500 queue down')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows an unknown run as such, without a dialog, and stops polling', async () => {
    const unknown = { detail: "no warm-up run 'nope' was recorded on this knowledge base" };
    const api = fakeApi({ ...KINDS, 'GET /warmup/nope': () => Response.json(unknown, { status: 404 }) });
    await renderRoute('/admin?run=nope', api);

    expect((await screen.findByRole('alert')).textContent).toBe('This warm-up run is not known');
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(calls(api, 'GET', '/warmup/nope')).toBe(1);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(button().disabled).toBe(false);
  });

  it('shows any other failed poll inline after its retries', async () => {
    const api = fakeApi({ ...KINDS, 'GET /warmup/r1': () => Response.json({ detail: 'store down' }, { status: 500 }) });
    await renderRoute('/admin?run=r1', api, new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } }));

    expect((await screen.findByRole('alert')).textContent).toBe('Progress unknown: 500 store down');
    expect(calls(api, 'GET', '/warmup/r1')).toBe(4);
  });
});
