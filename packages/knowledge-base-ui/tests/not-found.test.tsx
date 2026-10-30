import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { fakeApi, kinds, page } from './fake-api';
import { renderRoute } from './render-route';

const api = () => fakeApi({ 'GET /kinds': () => Response.json(kinds), 'GET /memory/knowledge': () => page([]) });

describe('not found', () => {
  it.each(['/recipes', '/no/such/path'])('renders "No such kind" for %s inside the layout', async (path) => {
    const fake = api();
    await renderRoute(path, fake);

    expect(await screen.findByRole('heading', { level: 1, name: 'No such kind' })).toBeTruthy();
    // The kind is refused before the list loader runs.
    expect(fake.requests.map((r) => new URL(r.url).pathname)).toEqual(['/api/kinds']);
    const nav = screen.getByRole('navigation');
    expect(within(nav).getByRole('link', { name: 'Knowledge' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Toggle theme' })).toBeTruthy();
    const links = within(screen.getByRole('main')).getAllByRole('link');
    expect(links.map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
      ['knowledge', '/knowledge'],
      ['entity', '/entity'],
    ]);
  });

  it('redirects / to the first kind', async () => {
    const { router } = await renderRoute('/', api());

    expect(router.state.location.pathname).toBe('/knowledge');
    expect(screen.getByRole('link', { name: 'Knowledge' }).dataset['active']).toBe('true');
  });
});
