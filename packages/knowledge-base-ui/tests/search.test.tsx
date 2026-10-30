import { act, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { MemoryHit } from '@/lib/api';

import { fact, fakeApi, kinds } from './fake-api';
import { renderRoute } from './render-route';

const hits: MemoryHit[] = [
  { ...fact(1), score: 0.75 },
  { id: 'e1', kind: 'entity', updated_at: '2026-10-17T10:00:00Z', payload: {}, score: -0.1 },
];

function searchApi() {
  return fakeApi({ 'GET /kinds': () => Response.json(kinds), 'GET /search': () => Response.json(hits) });
}

const searches = (api: ReturnType<typeof searchApi>) =>
  api.requests
    .filter((r) => new URL(r.url).pathname === '/api/search')
    .map((r) => Object.fromEntries(new URL(r.url).searchParams));

describe('search failures', () => {
  it('fails a malformed URL param, naming it, instead of searching without it', async () => {
    const api = searchApi();
    await renderRoute('/search?q=tea&top_k=5000', api);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/An error occurred in Search: .*top_k/s)).toBeTruthy();
    expect(searches(api)).toEqual([]);
  });

  it.each([
    ['q=tea&q=coffee', 'q'],
    ['q=tea&top_k=5&top_k=6', 'top_k'],
  ])('fails a repeated param instead of searching one of its values: %s', async (query, param) => {
    const api = searchApi();
    await renderRoute(`/search?${query}`, api);

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(new RegExp(`An error occurred in Search: .*"${param}"`, 's'))).toBeTruthy();
    expect(searches(api)).toEqual([]);
  });

  it('fails a hit of a kind /kinds does not list instead of rendering it fieldless', async () => {
    const stray: MemoryHit = { ...fact(1), id: 'r1', kind: 'recipe', score: 0.5 };
    const api = fakeApi({ 'GET /kinds': () => Response.json(kinds), 'GET /search': () => Response.json([stray]) });
    await renderRoute('/search?q=tea', api);

    expect(
      await screen.findByRole('dialog', { name: 'Error: Unknown kind "recipe"; /kinds lists ["knowledge","entity"]' }),
    ).toBeTruthy();
  });
});

describe('search', () => {
  // Cosine of an exact match comes back as 1.00000002.
  it('fills the bar for a score just above 1 instead of emptying it', async () => {
    const exact: MemoryHit = { ...fact(1), score: 1.0000002 };
    const api = fakeApi({ 'GET /kinds': () => Response.json(kinds), 'GET /search': () => Response.json([exact]) });
    await renderRoute('/search?q=tea', api);

    const bar = await screen.findByRole('progressbar');
    expect(bar.getAttribute('aria-label')).toBe('score 1.00');
    expect(bar.getAttribute('aria-valuenow')).toBe('100');
  });

  it('sends the URL params to the API and renders each hit with its score', async () => {
    const api = searchApi();
    await renderRoute('/search?q=tea&kind=knowledge&top_k=5&min_score=0.5', api);

    expect(searches(api)).toEqual([{ q: 'tea', kind: 'knowledge', top_k: '5', min_score: '0.5' }]);
    expect(screen.getByLabelText<HTMLInputElement>('Query').value).toBe('tea');
    expect(screen.getByLabelText<HTMLInputElement>('Top k').value).toBe('5');

    const [first, second] = screen.getAllByRole('progressbar');
    expect(first?.getAttribute('aria-label')).toBe('score 0.75');
    expect(first?.getAttribute('aria-valuenow')).toBe('75');
    const bar = first?.querySelector<HTMLElement>('[data-slot="progress-indicator"]');
    expect(bar?.style.transform).toBe('translateX(-25%)');
    expect(second?.getAttribute('aria-label')).toBe('score -0.10');
    expect(second?.getAttribute('aria-valuenow')).toBe('0');
    expect(screen.getByText('0.75')).toBeTruthy();
    const card = first?.closest('[data-slot="card"]') as HTMLElement;
    expect(within(card).getByText('knowledge')).toBeTruthy();
    expect(within(card).getByText('Category').nextSibling?.textContent).toBe('fact');
    expect(within(card).getByText('Content').nextSibling?.textContent).toBe('Fact 1');
  });

  it.each(['true', '1e5', '1.50', '[1]'])('searches a typed ?q=%s as that text', async (q) => {
    const api = searchApi();
    await renderRoute(`/search?q=${encodeURIComponent(q)}`, api);

    await waitFor(() => {
      expect(searches(api)).toEqual([{ q }]);
    });
    expect(screen.getByLabelText<HTMLInputElement>('Query').value).toBe(q);
  });

  it('puts the form in the URL, "All kinds" meaning no kind', async () => {
    const api = searchApi();
    const { user, router } = await renderRoute('/search', api);

    expect(searches(api)).toEqual([]);
    await user.type(screen.getByLabelText('Query'), 'tea');
    await user.type(screen.getByLabelText('Top k'), '3');
    await user.type(screen.getByLabelText('Min score'), '0.4');
    await user.click(screen.getByRole('combobox', { name: 'Kind' }));
    await user.click(await screen.findByRole('option', { name: 'entity' }));
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => {
      expect(router.state.location.search).toEqual({ q: 'tea', kind: 'entity', top_k: 3, min_score: 0.4 });
    });
    expect(await screen.findAllByRole('progressbar')).toHaveLength(2);

    await user.click(screen.getByRole('combobox', { name: 'Kind' }));
    await user.click(await screen.findByRole('option', { name: 'All kinds' }));
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => {
      expect(router.state.location.search).toEqual({ q: 'tea', top_k: 3, min_score: 0.4 });
    });
    expect(searches(api)).toEqual([
      { q: 'tea', kind: 'entity', top_k: '3', min_score: '0.4' },
      { q: 'tea', top_k: '3', min_score: '0.4' },
    ]);
  });

  it('leaves a blank Top k and Min score out of the URL, for the API default', async () => {
    const api = searchApi();
    const { user, router } = await renderRoute('/search', api);

    await user.type(screen.getByLabelText('Query'), 'tea');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => {
      expect(searches(api)).toEqual([{ q: 'tea' }]);
    });
    expect(router.state.location.search).toEqual({ q: 'tea' });
  });

  it('writes typed JSON-like text to the URL unquoted', async () => {
    const api = searchApi();
    const { user, router } = await renderRoute('/search', api);

    await user.type(screen.getByLabelText('Query'), 'true');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => {
      expect(searches(api)).toEqual([{ q: 'true' }]);
    });
    expect(router.state.location.searchStr).toBe('?q=true');
  });
});

describe('search history', () => {
  it('shows the earlier query in the form after Back', async () => {
    const api = searchApi();
    const { user, router } = await renderRoute('/search', api);
    const query = () => screen.getByLabelText<HTMLInputElement>('Query');

    await user.type(query(), 'tea');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await user.clear(query());
    await user.type(query(), 'coffee');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ q: 'coffee' });
    });

    act(() => {
      router.history.back();
    });
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ q: 'tea' });
    });
    await waitFor(() => {
      expect(query().value).toBe('tea');
    });
  });
});
