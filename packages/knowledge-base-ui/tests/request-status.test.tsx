import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory, createRootRouteWithContext, createRouter, RouterProvider } from '@tanstack/react-router';
import { act, render, screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { vi } from 'vitest';

import { PendingRequests, usePending } from '@/components/PendingRequests';
import { ThemeProvider } from '@/components/theme-provider';
import { Toaster } from '@/components/ui/sonner';
import { createApi, type RequestState } from '@/lib/api';
import type { RouterContext } from '@/router';

import { type FakeApi, fakeApi, kinds } from './fake-api';
import { renderRoute } from './render-route';

const REQUEST = 'GET /requests/r1';
const KINDS = { 'GET /kinds': () => Response.json(kinds) };

// Answers each state in turn, then repeats the last.
function states(...answers: RequestState[]) {
  const queue = [...answers];
  return () => Response.json(queue.length > 1 ? queue.shift() : queue[0]);
}

const queued: RequestState = { request_id: 'r1', status: 'queued', error: null };
const done: RequestState = { request_id: 'r1', status: 'done', error: null };
const failed: RequestState = { request_id: 'r1', status: 'failed', error: 'APIConnectionError: Connection error.' };

const polls = (api: FakeApi) => api.requests.filter((r) => new URL(r.url).pathname === '/api/requests/r1').length;

// Only the poll's interval is faked; testing-library's waits keep real timeouts.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
});
afterEach(() => {
  vi.useRealTimers();
});

describe('request status page', () => {
  it('polls while queued and stops once done', async () => {
    const api = fakeApi({ ...KINDS, [REQUEST]: states(queued, done) });
    await renderRoute('/requests/r1', api);

    expect(await screen.findByText('queued')).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(await screen.findByText('done')).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(5000));

    expect(polls(api)).toBe(2);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows a failed request with its error', async () => {
    await renderRoute('/requests/r1', fakeApi({ ...KINDS, [REQUEST]: states(failed) }));

    expect(await screen.findByText('failed')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBe('APIConnectionError: Connection error.');
  });

  it('shows an unknown request as such and stops polling', async () => {
    const api = fakeApi({
      ...KINDS,
      [REQUEST]: () => Response.json({ detail: 'Unknown request r1' }, { status: 404 }),
    });
    await renderRoute('/requests/r1', api);

    expect((await screen.findByRole('alert')).textContent).toBe('Status unknown: 404 Unknown request r1');
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(polls(api)).toBe(1);
  });

  it('drops the last-known badge once a later poll fails', async () => {
    const answers = [Response.json(queued), Response.json({ detail: 'store down' }, { status: 500 })];
    await renderRoute('/requests/r1', fakeApi({ ...KINDS, [REQUEST]: () => answers.shift() ?? Response.json(queued) }));

    expect(await screen.findByText('queued')).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect((await screen.findByRole('alert')).textContent).toBe('Status unknown: 500 store down');
    expect(screen.queryByText('queued')).toBeNull();
  });
});

function Tracker() {
  const { pending, track } = usePending();
  return (
    <button
      type="button"
      onClick={() => {
        track({ requestId: 'r1', kind: 'entity', itemIds: ['e1'], action: 'save' });
      }}
    >
      Track {pending.length}
    </button>
  );
}

function renderTracker(api: FakeApi) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRootRouteWithContext<RouterContext>()({
    component: () => (
      <ThemeProvider>
        <PendingRequests>
          <Tracker />
        </PendingRequests>
        <Toaster />
      </ThemeProvider>
    ),
  });
  const router = createRouter({
    routeTree: root,
    context: { queryClient, ...createApi(api.fetch) },
    history: createMemoryHistory(),
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { queryClient, router };
}

describe('PendingRequests', () => {
  const listKey = ['get', '/memory/{kind}', { params: { path: { kind: 'entity' } } }];

  it.each([
    [done, 'Saved'],
    [failed, 'Save failed'],
  ])('toasts a tracked request until it ends (%o), then invalidates its list', async (end, message) => {
    const { queryClient } = renderTracker(fakeApi({ [REQUEST]: states(queued, end) }));
    queryClient.setQueryData(listKey, { pages: [], pageParams: [] });

    await userEvent.click(await screen.findByRole('button', { name: 'Track 0' }));
    expect(await screen.findByText('Saving entity…')).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Track 1' })).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(1000));

    expect(await screen.findByText(message)).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Track 0' })).toBeTruthy();
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true);
  });

  it('toasts a poll that fails, releases the request and invalidates its list', async () => {
    const api = fakeApi({});
    const { queryClient } = renderTracker(api);
    queryClient.setQueryData(listKey, { pages: [], pageParams: [] });

    await userEvent.click(await screen.findByRole('button', { name: 'Track 0' }));

    expect(await screen.findByText('Save status unknown')).toBeTruthy();
    expect(screen.getByText('404 with no body')).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Track 0' })).toBeTruthy();
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true);
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(polls(api)).toBe(1);
  });

  it("opens the request's status page from the toast", async () => {
    const { router } = renderTracker(fakeApi({ [REQUEST]: states(queued) }));

    await userEvent.click(await screen.findByRole('button', { name: 'Track 0' }));
    await userEvent.click(await screen.findByRole('button', { name: 'View status' }));

    expect(router.state.location.pathname).toBe('/requests/r1');
  });

  it('throws outside the provider', () => {
    expect(() => render(<Tracker />)).toThrow('usePending must be used within PendingRequests');
  });
});
