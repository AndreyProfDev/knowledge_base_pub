import { screen, waitFor, within } from '@testing-library/react';
import { agTestIdFor } from 'ag-grid-community';
import { describe, expect, it } from 'vitest';

import { fact, facts, fakeApi, kinds, page } from './fake-api';
import { renderRoute } from './render-route';

describe('route error', () => {
  it('opens ErrorDialog on a failed loader; Retry re-runs it and the rows render', async () => {
    const answers = [new Response(null, { status: 503, statusText: 'Service Unavailable' }), page(facts(0, 2))];
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => answers.shift() ?? page([]),
    });
    const { user } = await renderRoute('/knowledge', api);

    const dialog = await screen.findByRole('dialog', { name: 'Error: 503 Service Unavailable' });
    expect(within(dialog).getByText('An error occurred in Item list: 503 Service Unavailable')).toBeTruthy();
    await user.click(within(dialog).getByRole('button', { name: 'Retry' }));

    expect((await screen.findByTestId(agTestIdFor.cell(fact(1).id, 'content'))).textContent).toBe('Fact 1');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(answers).toEqual([]);
  });

  it('closes the dialog on Retry while the retried loader is still in flight', async () => {
    let release = () => undefined as unknown;
    const answers = [
      new Response(null, { status: 503, statusText: 'Service Unavailable' }),
      new Promise<Response>((resolve) => {
        release = () => {
          resolve(page(facts(0, 2)));
        };
      }),
    ];
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => answers.shift() ?? page([]),
    });
    const { user } = await renderRoute('/knowledge', api);

    const dialog = await screen.findByRole('dialog', { name: 'Error: 503 Service Unavailable' });
    await user.click(within(dialog).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
    expect(answers).toEqual([]);
    release();
    expect((await screen.findByTestId(agTestIdFor.cell(fact(1).id, 'content'))).textContent).toBe('Fact 1');
  });

  it('reopens the dialog when the retried loader fails again', async () => {
    const answers = [
      new Response(null, { status: 503, statusText: 'Service Unavailable' }),
      new Response(null, { status: 502, statusText: 'Bad Gateway' }),
    ];
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => answers.shift() ?? page([]),
    });
    const { user } = await renderRoute('/knowledge', api);

    const dialog = await screen.findByRole('dialog', { name: 'Error: 503 Service Unavailable' });
    await user.click(within(dialog).getByRole('button', { name: 'Retry' }));

    expect(await screen.findByRole('dialog', { name: 'Error: 502 Bad Gateway' })).toBeTruthy();
  });

  it("names the API's detail, not [object Object]", async () => {
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => Response.json({ detail: 'store down' }, { status: 500 }),
    });
    await renderRoute('/knowledge', api);

    const dialog = await screen.findByRole('dialog', { name: 'Error: 500 store down' });
    expect(within(dialog).getByText('An error occurred in Item list: 500 store down')).toBeTruthy();
  });

  it('cuts a long message to 100 characters in the title, not in the description', async () => {
    const detail = 'x'.repeat(150);
    const api = fakeApi({
      'GET /kinds': () => Response.json(kinds),
      'GET /memory/knowledge': () => Response.json({ detail }, { status: 500 }),
    });
    await renderRoute('/knowledge', api);

    const message = `500 ${detail}`;
    const dialog = await screen.findByRole('dialog', { name: `Error: ${message.slice(0, 100)}` });
    expect(within(dialog).getByText(`An error occurred in Item list: ${message}`)).toBeTruthy();
  });
});
