import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory, createRootRouteWithContext, createRouter, RouterProvider } from '@tanstack/react-router';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { agTestIdFor } from 'ag-grid-community';
import { describe, expect, it } from 'vitest';

import { ItemGrid } from '@/components/ItemGrid';
import { PendingRequests, usePending } from '@/components/PendingRequests';
import { ThemeProvider } from '@/components/theme-provider';
import { createApi, type MemoryItem } from '@/lib/api';
import { payloadSchema } from '@/lib/kinds';
import type { RouterContext } from '@/router';

import { fact, facts, type FakeApi, fakeApi, kinds, page } from './fake-api';
import { renderRoute } from './render-route';

// Page one ends at a cursor; the next page ends the list.
function pagedApi(): FakeApi {
  return fakeApi({
    'GET /kinds': () => Response.json(kinds),
    'GET /memory/knowledge': (req) =>
      new URL(req.url).searchParams.get('cursor') === 'c1' ? page(facts(50, 57)) : page(facts(0, 50), 'c1'),
  });
}

// The grid renders, then tags, asynchronously.
const cell = (n: number, colId: string) => screen.findByTestId(agTestIdFor.cell(fact(n).id, colId));
const header = (colId: string) => screen.findByTestId(agTestIdFor.headerCell(colId));

async function rowCount() {
  const panel = await screen.findByTestId(agTestIdFor.statusBarTotalAndFilteredRowCount());
  return panel.textContent.replace(/\s+/g, ' ').replace(' :', ':').trim();
}

describe('item list', () => {
  it('renders page one with its row count and more available', async () => {
    await renderRoute('/knowledge', pagedApi());

    expect(await screen.findByRole('grid', { name: 'Knowledge' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Knowledge' })).toBeTruthy();
    expect((await cell(0, 'content')).textContent).toBe('Fact 0');
    expect((await cell(0, 'id')).textContent).toBe('k0000-00');
    expect(await rowCount()).toBe('Rows: 50');
    expect(screen.getByText('more available')).toBeTruthy();
  });

  it('loads the next page from next_cursor and appends it', async () => {
    const api = pagedApi();
    const { user } = await renderRoute('/knowledge', api);

    await user.click(await screen.findByRole('button', { name: 'Load more' }));

    expect(await screen.findByText('all loaded')).toBeTruthy();
    // jsdom has no layout, so the grid renders only the first rows; the count shows the append.
    expect(await rowCount()).toBe('Rows: 57');
    expect((await cell(0, 'content')).textContent).toBe('Fact 0');
    const cursors = api.requests
      .filter((r) => new URL(r.url).pathname === '/api/memory/knowledge')
      .map((r) => new URL(r.url).searchParams.get('cursor'));
    expect(cursors).toEqual([null, 'c1']);
  });

  it('shows a failed next page in the panel and retries that page', async () => {
    const answers = [page(facts(0, 50), 'c1'), new Response(null, { status: 502, statusText: 'Bad Gateway' })];
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => answers.shift() ?? page(facts(50, 57)),
    });
    const { user } = await renderRoute('/knowledge', api);

    await user.click(await screen.findByRole('button', { name: 'Load more' }));

    expect((await screen.findByRole('alert')).textContent).toBe('Load failed: 502 Bad Gateway');
    expect(screen.queryByText('more available')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('all loaded')).toBeTruthy();
    expect(await rowCount()).toBe('Rows: 57');
  });

  it('sorts Updated and filters enums only once every page is in', async () => {
    const { user } = await renderRoute('/knowledge', pagedApi());

    expect((await header('updated_at')).getAttribute('aria-sort')).toBeNull();
    expect(screen.queryByTestId(agTestIdFor.headerFilterButton('category'))).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Load more' }));
    await screen.findByText('all loaded');

    expect(await screen.findByTestId(agTestIdFor.headerFilterButton('category'))).toBeTruthy();
    expect((await header('updated_at')).getAttribute('aria-sort')).toBe('none');
    expect((await header('content')).getAttribute('aria-sort')).toBeNull();
    expect(screen.queryByTestId(agTestIdFor.headerFilterButton('content'))).toBeNull();
  });

  it('opens the delete dialog from the right-click menu', async () => {
    const { user } = await renderRoute('/knowledge', pagedApi());

    fireEvent.contextMenu(await cell(3, 'content'));
    await user.click(await screen.findByTestId(agTestIdFor.menuOption('Delete')));

    const dialog = await screen.findByRole('alertdialog', { name: 'Delete this knowledge?' });
    expect(within(dialog).getByText('Fact 3').tagName).toBe('STRONG');
  });

  it('shows the empty card instead of a grid', async () => {
    await renderRoute(
      '/knowledge',
      fakeApi({ 'GET /kinds': () => Response.json(kinds), 'GET /memory/knowledge': () => page([]) }),
    );

    expect(await screen.findByText('No knowledge items yet.')).toBeTruthy();
    expect(screen.queryByRole('grid')).toBeNull();
  });

  it("navigates Edit to the item's edit page", async () => {
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => page(facts(0, 3)),
      [`GET /memory/knowledge/${fact(2).id}`]: () => Response.json(fact(2)),
    });
    const { router, user } = await renderRoute('/knowledge', api);

    const actions = await cell(2, 'actions');
    await user.click(within(actions).getByRole('button', { name: 'Open menu' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Edit' }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/knowledge/${fact(2).id}/edit`);
    });
    expect(await screen.findByRole('button', { name: 'Save' })).toBeTruthy();
  });
});

// A queued request on fact 0, started the way a form submit starts one.
function Lock() {
  const { track } = usePending();
  return (
    <button
      type="button"
      onClick={() => {
        track({ requestId: 'r1', kind: 'knowledge', itemIds: [fact(0).id], action: 'save' });
      }}
    >
      Lock
    </button>
  );
}

function renderGrid(edits: string[]) {
  const api = fakeApi({ 'GET /requests/r1': () => Response.json({ request_id: 'r1', status: 'queued', error: null }) });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const edit = (item: MemoryItem) => edits.push(item.id);
  const root = createRootRouteWithContext<RouterContext>()({
    component: () => (
      <ThemeProvider>
        <PendingRequests>
          <Lock />
          <ItemGrid
            kind="knowledge"
            schema={payloadSchema(kinds, 'knowledge')}
            rows={facts(0, 2)}
            paging={{
              hasNextPage: false,
              isFetching: false,
              fetchNextPage: () => undefined,
              loadError: null,
              retry: () => undefined,
            }}
            edit={edit}
            confirmDelete={() => undefined}
          />
        </PendingRequests>
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
}

describe('edit lock', () => {
  it('disables Edit in the row menu and the context menu while the row has a queued request', async () => {
    const edits: string[] = [];
    renderGrid(edits);
    const user = userEvent.setup();
    const openRowMenu = async () => {
      await user.click(within(await cell(0, 'actions')).getByRole('button', { name: 'Open menu' }));
      return screen.findByRole('menuitem', { name: 'Edit' });
    };

    await user.click(await openRowMenu());
    expect(edits).toEqual([fact(0).id]);

    await user.click(screen.getByRole('button', { name: 'Lock' }));
    expect((await openRowMenu()).dataset['disabled']).toBe('');
    await user.keyboard('{Escape}');
    fireEvent.contextMenu(await cell(0, 'content'));
    const contextEdit = await screen.findByTestId(agTestIdFor.menuOption('Edit'));
    expect(contextEdit.getAttribute('aria-disabled')).toBe('true');
  });
});
