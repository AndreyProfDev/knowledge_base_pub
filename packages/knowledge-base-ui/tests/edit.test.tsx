import { act, screen, waitFor, within } from '@testing-library/react';
import { agTestIdFor } from 'ag-grid-community';
import { describe, expect, it } from 'vitest';

import type { RequestState, WriteAccepted } from '@/lib/api';

import { fact, facts, fakeApi, kinds, page } from './fake-api';
import { renderRoute } from './render-route';

const ITEM = `/memory/knowledge/${fact(1).id}`;
const accepted: WriteAccepted = { request_id: 'r1', item_id: fact(1).id, status: 'queued' };
const queued: RequestState = { request_id: 'r1', status: 'queued', error: null };
const tooLong = 'Payload is over the embedder token limit';

function editApi(write: () => Response | Promise<Response>) {
  return fakeApi({
    'GET /kinds': () => Response.json(kinds),
    'GET /memory/knowledge': () => page(facts(0, 3)),
    [`GET ${ITEM}`]: () => Response.json(fact(1)),
    [`PUT ${ITEM}`]: write,
    'POST /memory/knowledge': write,
    'GET /requests/r1': () => Response.json(queued),
  });
}

const writes = (api: ReturnType<typeof editApi>, method: string) => api.requests.filter((r) => r.method === method);

describe('edit', () => {
  it('prefills from GET and submits the whole payload with PUT', async () => {
    const api = editApi(() => Response.json(accepted, { status: 202 }));
    const { user, router } = await renderRoute(`/knowledge/${fact(1).id}/edit`, api);

    expect(screen.getByRole('heading', { name: 'Edit knowledge' })).toBeTruthy();
    const content = await screen.findByLabelText('Content');
    expect((content as HTMLTextAreaElement).value).toBe('Fact 1');
    await user.clear(content);
    await user.type(content, 'Fact one');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Saving knowledge…')).toBeTruthy();
    expect(router.state.location.pathname).toBe('/knowledge');
    const [put] = writes(api, 'PUT');
    expect(await put?.json()).toEqual({ category: 'fact', content: 'Fact one' });
  });

  it('keeps Edit disabled while the request is queued, on the old id of a key-changing edit', async () => {
    const rekeyed: WriteAccepted = { ...accepted, item_id: fact(9).id };
    const api = editApi(() => Response.json(rekeyed, { status: 202 }));
    const { user, router } = await renderRoute(`/knowledge/${fact(1).id}/edit`, api);

    await user.click(await screen.findByRole('button', { name: 'Save' }));
    const actions = await screen.findByTestId(agTestIdFor.cell(fact(1).id, 'actions'));
    await user.click(within(actions).getByRole('button', { name: 'Open menu' }));

    const edit = await screen.findByRole('menuitem', { name: 'Edit' });
    expect(edit.getAttribute('aria-disabled')).toBe('true');

    // Its edit URL, opened directly, cannot submit either.
    await user.keyboard('{Escape}');
    await act(() => router.navigate({ to: '/$kind/$id/edit', params: { kind: 'knowledge', id: fact(1).id } }));
    expect((await screen.findByRole('button', { name: 'Save' })).hasAttribute('disabled')).toBe(true);
  });

  it('shows the written payload, not the pre-write one, once the lock lifts', async () => {
    let done = false;
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => page(facts(0, 3)),
      [`GET ${ITEM}`]: () =>
        Response.json(done ? { ...fact(1), payload: { category: 'fact', content: 'Fact one' } } : fact(1)),
      [`PUT ${ITEM}`]: () => Response.json(accepted, { status: 202 }),
      'GET /requests/r1': () => Response.json({ ...queued, status: done ? 'done' : 'queued' }),
    });
    const { user, router } = await renderRoute(`/knowledge/${fact(1).id}/edit`, api);

    await user.click(await screen.findByRole('button', { name: 'Save' }));
    await screen.findByText('Saving knowledge…');
    await act(() => router.navigate({ to: '/$kind/$id/edit', params: { kind: 'knowledge', id: fact(1).id } }));
    expect((await screen.findByRole('button', { name: 'Save' })).hasAttribute('disabled')).toBe(true);

    done = true;
    await waitFor(
      () => {
        expect(screen.getByRole('button', { name: 'Save' }).hasAttribute('disabled')).toBe(false);
      },
      { timeout: 3000 },
    );
    expect(screen.getByLabelText<HTMLTextAreaElement>('Content').value).toBe('Fact one');
  });

  it("shows a 422's msg in the form's error list", async () => {
    const detail = [{ loc: ['body', 'content'], msg: tooLong, type: 'value_error' }];
    const api = editApi(() => Response.json({ detail }, { status: 422 }));
    const { user, router } = await renderRoute(`/knowledge/${fact(1).id}/edit`, api);

    await user.click(await screen.findByRole('button', { name: 'Save' }));

    const errorList = await screen.findByRole('alert');
    expect(within(errorList).getByText('Errors')).toBeTruthy();
    expect(errorList.textContent).toContain(tooLong);
    expect(router.state.location.pathname).toBe(`/knowledge/${fact(1).id}/edit`);
  });

  it('shows any other failure, with its status and detail, and stays on the form', async () => {
    const api = editApi(() => Response.json({ detail: 'store down' }, { status: 500 }));
    const { user, router } = await renderRoute(`/knowledge/${fact(1).id}/edit`, api);

    await user.click(await screen.findByRole('button', { name: 'Save' }));

    const errorList = await screen.findByRole('alert');
    expect(errorList.textContent).toContain('Save failed: 500 store down');
    expect(router.state.location.pathname).toBe(`/knowledge/${fact(1).id}/edit`);
  });
});

describe('add', () => {
  it('posts the form to the kind and tracks the request', async () => {
    const api = editApi(() => Response.json({ ...accepted, item_id: fact(9).id }, { status: 202 }));
    const { user, router } = await renderRoute('/knowledge/new', api);

    expect(screen.getByRole('heading', { name: 'Add knowledge' })).toBeTruthy();
    await user.type(await screen.findByLabelText('Content'), 'Tea is green');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    expect(await screen.findByText('Saving knowledge…')).toBeTruthy();
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/knowledge');
    });
    const [post] = writes(api, 'POST');
    expect(await post?.json()).toEqual({ content: 'Tea is green' });
  });

  it("shows a 422's msg in the add form's error list", async () => {
    const detail = [{ loc: ['body', 'content'], msg: tooLong, type: 'value_error' }];
    const { user, router } = await renderRoute(
      '/knowledge/new',
      editApi(() => Response.json({ detail }, { status: 422 })),
    );

    await user.type(await screen.findByLabelText('Content'), 'Tea is green');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    expect((await screen.findByRole('alert')).textContent).toContain(tooLong);
    expect(router.state.location.pathname).toBe('/knowledge/new');
  });
});

describe('write in flight', () => {
  it.each([
    ['POST', '/knowledge/new', 'Add'],
    ['PUT', `/knowledge/${fact(1).id}/edit`, 'Save'],
  ])('disables the form while the %s is in flight', async (_method, path, submit) => {
    let release = () => undefined as unknown;
    const held = new Promise<Response>((resolve) => {
      release = () => {
        resolve(Response.json({ ...accepted, item_id: fact(9).id }, { status: 202 }));
      };
    });
    const { user } = await renderRoute(
      path,
      editApi(() => held),
    );

    await user.type(await screen.findByLabelText('Content'), 'Tea is green');
    await user.click(screen.getByRole('button', { name: submit }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: submit }).hasAttribute('disabled')).toBe(true);
    });
    release();
    expect(await screen.findByText('Saving knowledge…')).toBeTruthy();
  });

  it('tracks a write that lands after leaving the form, without navigating back', async () => {
    let release = () => undefined as unknown;
    const held = new Promise<Response>((resolve) => {
      release = () => {
        resolve(Response.json({ ...accepted, item_id: fact(9).id }, { status: 202 }));
      };
    });
    const { user, router } = await renderRoute(
      '/knowledge/new',
      editApi(() => held),
    );

    await user.type(await screen.findByLabelText('Content'), 'Tea is green');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await act(() => router.navigate({ to: '/search' }));
    release();

    expect(await screen.findByText('Saving knowledge…')).toBeTruthy();
    expect(router.state.location.pathname).toBe('/search');
  });
});
