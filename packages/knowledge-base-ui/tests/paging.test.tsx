import { act, screen, waitFor, within } from '@testing-library/react';
import { agTestIdFor } from 'ag-grid-community';
import { describe, expect, it } from 'vitest';

import { listQueryKey } from '@/lib/list-query';

import { deleted, deleteRequest, fact, facts, fakeApi, kinds, page } from './fake-api';
import { renderRoute } from './render-route';

async function deleteFact1(user: Awaited<ReturnType<typeof renderRoute>>['user']) {
  const actions = await screen.findByTestId(agTestIdFor.cell(fact(1).id, 'actions'));
  await user.click(within(actions).getByRole('button', { name: 'Open menu' }));
  await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));
  await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
}

describe('paging in flight', () => {
  it('disables Load more while the next page is in flight', async () => {
    let release = () => undefined as unknown;
    const held = new Promise<Response>((resolve) => {
      release = () => {
        resolve(page(facts(50, 57)));
      };
    });
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': (req) => (new URL(req.url).searchParams.has('cursor') ? held : page(facts(0, 50), 'c1')),
    });
    const { user } = await renderRoute('/knowledge', api);

    await user.click(await screen.findByRole('button', { name: 'Load more' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Load more' }).hasAttribute('disabled')).toBe(true);
    });
    release();
    expect(await screen.findByText('all loaded')).toBeTruthy();
  });
});

describe('list re-entry', () => {
  it('keeps the cached grid and shows a failed refetch in the panel', async () => {
    let fail = false;
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': (req) => {
        if (fail) return new Response(null, { status: 502, statusText: 'Bad Gateway' });
        return new URL(req.url).searchParams.has('cursor') ? page(facts(50, 57)) : page(facts(0, 50), 'c1');
      },
    });
    const { user, router } = await renderRoute('/knowledge', api);
    await user.click(await screen.findByRole('button', { name: 'Load more' }));
    await screen.findByText('all loaded');

    await act(() => router.navigate({ to: '/$kind/new', params: { kind: 'knowledge' } }));
    fail = true;
    await act(() => router.options.context.queryClient.invalidateQueries({ queryKey: listQueryKey('knowledge') }));
    await act(() => router.navigate({ to: '/$kind', params: { kind: 'knowledge' } }));

    expect((await screen.findByRole('alert')).textContent).toBe('Load failed: 502 Bad Gateway');
    expect(screen.getByRole('grid', { name: 'Knowledge' })).toBeTruthy();
  });
});

describe('paging during a refetch', () => {
  // Load more would cancel the refetch, keeping the deleted row on the stale first page.
  it('disables Load more while a refetch after a delete is in flight', async () => {
    let items = facts(0, 50);
    let release = () => undefined as unknown;
    let firstPages = 0;
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': (req) => {
        if (new URL(req.url).searchParams.has('cursor')) return page(facts(50, 52));
        firstPages += 1;
        if (firstPages === 1) return page(items, 'c1');
        return new Promise<Response>((resolve) => {
          release = () => {
            resolve(page(items, 'c1'));
          };
        });
      },
      [`DELETE /memory/knowledge/${fact(1).id}`]: () => {
        items = items.filter((i) => i.id !== fact(1).id);
        return deleted();
      },
      'GET /requests/d1': () => deleteRequest('done'),
    });
    const { user } = await renderRoute('/knowledge', api);
    await deleteFact1(user);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Load more' }).hasAttribute('disabled')).toBe(true);
    });
    release();
    await waitFor(() => {
      expect(screen.queryByTestId(agTestIdFor.cell(fact(1).id, 'content'))).toBeNull();
    });
    expect(screen.getByRole('button', { name: 'Load more' }).hasAttribute('disabled')).toBe(false);
  });

  it('disables Retry while the retried refetch is in flight', async () => {
    let release = () => undefined as unknown;
    const answers: (Response | Promise<Response>)[] = [
      page(facts(0, 50), 'c1'),
      new Response(null, { status: 502, statusText: 'Bad Gateway' }),
      new Promise<Response>((resolve) => {
        release = () => {
          resolve(page(facts(0, 3)));
        };
      }),
    ];
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => answers.shift() ?? page(facts(0, 3)),
      [`DELETE /memory/knowledge/${fact(1).id}`]: deleted,
      'GET /requests/d1': () => deleteRequest('done'),
    });
    const { user } = await renderRoute('/knowledge', api);
    await deleteFact1(user);

    expect((await screen.findByRole('alert')).textContent).toBe('Load failed: 502 Bad Gateway');
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Retry' }).hasAttribute('disabled')).toBe(true);
    });
    release();
    expect(await screen.findByText('all loaded')).toBeTruthy();
  });

  // A refetch can add a next_cursor (a page of 50 grew to 51); the sort must go with its header.
  it('drops the Updated sort when a refetch makes the list incomplete again', async () => {
    const rows = [0, 1, 2].map((n) => ({ ...fact(n), updated_at: `2026-10-1${String(n)}T10:00:00Z` }));
    const answers = [page(rows)];
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => answers.shift() ?? page(rows, 'c1'),
    });
    const { router, user } = await renderRoute('/knowledge', api);
    const topRow = () => document.querySelector('[row-index="0"][row-id]')?.getAttribute('row-id');

    const updated = await screen.findByTestId(agTestIdFor.headerCell('updated_at'));
    await user.click(within(updated).getByText('Updated'));
    await waitFor(() => {
      expect(topRow()).toBe(fact(2).id);
    });
    await act(() => router.options.context.queryClient.invalidateQueries({ queryKey: listQueryKey('knowledge') }));
    await screen.findByText('more available');

    await waitFor(() => {
      expect(topRow()).toBe(fact(0).id);
    });
  });
});
