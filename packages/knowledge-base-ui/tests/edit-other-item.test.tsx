import { act, screen, waitFor, within } from '@testing-library/react';
import { agTestIdFor } from 'ag-grid-community';
import { describe, expect, it } from 'vitest';

import type { RequestState, WriteAccepted } from '@/lib/api';

import { fact, facts, fakeApi, kinds, page } from './fake-api';
import { renderRoute } from './render-route';

const A = `/memory/knowledge/${fact(1).id}`;
const B = `/memory/knowledge/${fact(2).id}`;
const rekeyed: WriteAccepted = { request_id: 'r1', item_id: fact(2).id, status: 'queued' };
const queued: RequestState = { request_id: 'r1', status: 'queued', error: null };

// Edits A so its key becomes existing B's.
function rekeyApi(isDone: () => boolean) {
  return fakeApi({
    'GET /kinds': () => Response.json(kinds),
    'GET /memory/knowledge': () => page(facts(0, 3)),
    [`GET ${A}`]: () => Response.json(fact(1)),
    [`GET ${B}`]: () =>
      Response.json(isDone() ? { ...fact(2), payload: { category: 'fact', content: 'Fact 1' } } : fact(2)),
    [`PUT ${A}`]: () => Response.json(rekeyed, { status: 202 }),
    'GET /requests/r1': () => Response.json({ ...queued, status: isDone() ? 'done' : 'queued' }),
  });
}

describe('key-changing edit', () => {
  it("keeps Edit disabled on the row it writes to, when its new key's item exists", async () => {
    const { user } = await renderRoute(
      `/knowledge/${fact(1).id}/edit`,
      rekeyApi(() => false),
    );

    await user.click(await screen.findByRole('button', { name: 'Save' }));
    const actions = await screen.findByTestId(agTestIdFor.cell(fact(2).id, 'actions'));
    await user.click(within(actions).getByRole('button', { name: 'Open menu' }));

    const edit = await screen.findByRole('menuitem', { name: 'Edit' });
    expect(edit.getAttribute('aria-disabled')).toBe('true');
  });

  it("refetches its new key's item before the lock lifts", async () => {
    let done = false;
    const { user, router } = await renderRoute(
      `/knowledge/${fact(1).id}/edit`,
      rekeyApi(() => done),
    );

    await user.click(await screen.findByRole('button', { name: 'Save' }));
    await screen.findByText('Saving knowledge…');
    await act(() => router.navigate({ to: '/$kind/$id/edit', params: { kind: 'knowledge', id: fact(2).id } }));
    expect((await screen.findByRole('button', { name: 'Save' })).hasAttribute('disabled')).toBe(true);

    done = true;
    await waitFor(
      () => {
        expect(screen.getByRole('button', { name: 'Save' }).hasAttribute('disabled')).toBe(false);
      },
      { timeout: 3000 },
    );
    expect(screen.getByLabelText<HTMLTextAreaElement>('Content').value).toBe('Fact 1');
  });
});

describe('another item', () => {
  it("opened straight from an edit form, shows none of the first item's save failure", async () => {
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      [`GET ${A}`]: () => Response.json(fact(1)),
      [`PUT ${A}`]: () => Response.json({ detail: 'store down' }, { status: 500 }),
      [`GET ${B}`]: () => Response.json(fact(2)),
    });
    const { user, router } = await renderRoute(`/knowledge/${fact(1).id}/edit`, api);

    await user.click(await screen.findByRole('button', { name: 'Save' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Save failed: 500 store down');
    await act(() => router.navigate({ to: '/$kind/$id/edit', params: { kind: 'knowledge', id: fact(2).id } }));

    expect(await screen.findByDisplayValue('Fact 2')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
