import { screen, waitFor, within } from '@testing-library/react';
import { agTestIdFor } from 'ag-grid-community';
import { describe, expect, it } from 'vitest';

import { deleted, deleteRequest, fact, facts, fakeApi, kinds, page } from './fake-api';
import { renderRoute } from './render-route';

// The list loses an item once its DELETE lands; its dump-removal request ends as `request` says.
function deletableApi(request: () => Response = () => deleteRequest('done')) {
  let items = facts(0, 3);
  return fakeApi({
    'GET /kinds': () => Response.json(kinds),
    'GET /memory/knowledge': () => page(items),
    [`DELETE /memory/knowledge/${fact(1).id}`]: () => {
      items = items.filter((i) => i.id !== fact(1).id);
      return deleted();
    },
    'GET /requests/d1': request,
  });
}

async function openDeleteDialog(user: Awaited<ReturnType<typeof renderRoute>>['user']) {
  const actions = await screen.findByTestId(agTestIdFor.cell(fact(1).id, 'actions'));
  await user.click(within(actions).getByRole('button', { name: 'Open menu' }));
  await user.click(await screen.findByRole('menuitem', { name: 'Delete' }));
  return screen.findByRole('alertdialog', { name: 'Delete this knowledge?' });
}

describe('delete', () => {
  it('sends DELETE on confirm and drops the row', async () => {
    const api = deletableApi();
    const { user } = await renderRoute('/knowledge', api);

    const dialog = await openDeleteDialog(user);
    expect(within(dialog).getByText('Fact 1')).toBeTruthy();
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(screen.queryByTestId(agTestIdFor.cell(fact(1).id, 'content'))).toBeNull();
    });
    expect(screen.queryByRole('alertdialog')).toBeNull();
    const deletes = api.requests.filter((r) => r.method === 'DELETE').map((r) => new URL(r.url).pathname);
    expect(deletes).toEqual([`/api/memory/knowledge/${fact(1).id}`]);
    expect(screen.getByTestId(agTestIdFor.cell(fact(2).id, 'content')).textContent).toBe('Fact 2');
    expect(await screen.findByText('Deleted')).toBeTruthy();
  });

  it('toasts a failed dump-file removal with its error', async () => {
    const api = deletableApi(() => deleteRequest('failed', 'cannot remove dump file x.yaml'));
    const { user } = await renderRoute('/knowledge', api);

    const dialog = await openDeleteDialog(user);
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(await screen.findByText('Deleted, but its warm-up dump file remains')).toBeTruthy();
    expect(screen.getByText('cannot remove dump file x.yaml')).toBeTruthy();
  });

  it('toasts a failed DELETE with its status and detail, and keeps the row', async () => {
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => page(facts(0, 3)),
      [`DELETE /memory/knowledge/${fact(1).id}`]: () => new Response(null, { status: 404 }),
    });
    const { user } = await renderRoute('/knowledge', api);

    const dialog = await openDeleteDialog(user);
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(await screen.findByText('Delete returned an error')).toBeTruthy();
    expect(screen.getByText('404 with no body')).toBeTruthy();
    expect(screen.getByTestId(agTestIdFor.cell(fact(1).id, 'content')).textContent).toBe('Fact 1');
  });

  it('toasts a 500 whose detail says the item is gone without calling the delete failed', async () => {
    const detail = `knowledge item ${fact(1).id} deleted; dump file x.yaml not scheduled for removal`;
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => page(facts(0, 3)),
      [`DELETE /memory/knowledge/${fact(1).id}`]: () => Response.json({ detail }, { status: 500 }),
    });
    const { user } = await renderRoute('/knowledge', api);

    const dialog = await openDeleteDialog(user);
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(await screen.findByText('Delete returned an error')).toBeTruthy();
    expect(screen.getByText(detail, { exact: false })).toBeTruthy();
    expect(screen.queryByText('Delete failed', { exact: false })).toBeNull();
  });

  it('refetches the list after a failed DELETE, dropping a row deleted elsewhere', async () => {
    let items = facts(0, 3);
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => page(items),
      [`DELETE /memory/knowledge/${fact(1).id}`]: () => new Response(null, { status: 404 }),
    });
    const { user } = await renderRoute('/knowledge', api);

    const dialog = await openDeleteDialog(user);
    items = items.filter((i) => i.id !== fact(1).id);
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(await screen.findByText('Delete returned an error')).toBeTruthy();
    await waitFor(() => {
      expect(screen.queryByTestId(agTestIdFor.cell(fact(1).id, 'content'))).toBeNull();
    });
  });

  it('sends nothing on cancel', async () => {
    const api = deletableApi();
    const { user } = await renderRoute('/knowledge', api);

    const dialog = await openDeleteDialog(user);
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => {
      expect(screen.queryByRole('alertdialog')).toBeNull();
    });
    expect(api.requests.filter((r) => r.method === 'DELETE')).toEqual([]);
    expect(screen.getByTestId(agTestIdFor.cell(fact(1).id, 'content')).textContent).toBe('Fact 1');
  });
});
