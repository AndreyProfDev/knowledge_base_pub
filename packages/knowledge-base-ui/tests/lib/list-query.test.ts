import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { createApi } from '@/lib/api';
import { listQueryOptions } from '@/lib/list-query';

import { fakeApi } from '../fake-api';

const item = (id: string) => ({ id, kind: 'entity', updated_at: '2026-10-17T00:00:00Z', payload: {} });

describe('listQueryOptions', () => {
  it("keys the query as openapi-react-query keys the kind's list", () => {
    expect(listQueryOptions(createApi(fakeApi({}).fetch).fetchClient, 'entity').queryKey).toEqual([
      'get',
      '/memory/{kind}',
      { params: { path: { kind: 'entity' } } },
    ]);
  });

  it('pages forward with next_cursor until it is null', async () => {
    const { fetch, requests } = fakeApi({
      'GET /memory/entity': (req) =>
        Response.json(
          new URL(req.url).searchParams.has('cursor')
            ? { items: [item('b')], next_cursor: null }
            : { items: [item('a')], next_cursor: 'b' },
        ),
    });
    const api = createApi(fetch);
    const queryClient = new QueryClient();
    const options = listQueryOptions(api.fetchClient, 'entity');

    const data = await queryClient.infiniteQuery({ ...options, pages: 3 });
    const urls = requests.map((r) => new URL(r.url));

    expect(data.pages.flatMap((p) => p.items.map((i) => i.id))).toEqual(['a', 'b']);
    expect(data.pageParams).toEqual([null, 'b']);
    expect(urls.map((u) => u.pathname)).toEqual(['/api/memory/entity', '/api/memory/entity']);
    expect(urls[0]?.searchParams.get('limit')).toBe('50');
    expect(urls[0]?.searchParams.has('cursor')).toBe(false);
    expect(urls[1]?.searchParams.get('cursor')).toBe('b');
  });

  it('throws the error body of a failed page', async () => {
    const api = createApi(() => Promise.resolve(Response.json({ detail: 'down' }, { status: 503 })));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    await expect(queryClient.infiniteQuery(listQueryOptions(api.fetchClient, 'entity'))).rejects.toThrow('503 down');
  });

  it('throws on a 2xx page with no body', async () => {
    const api = createApi(() => Promise.resolve(new Response(null, { status: 200 })));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    await expect(queryClient.infiniteQuery(listQueryOptions(api.fetchClient, 'entity'))).rejects.toThrow(
      '200 page with no body',
    );
  });

  it('throws the status of a failed page with no body', async () => {
    const api = createApi(() =>
      Promise.resolve(new Response(null, { status: 503, statusText: 'Service Unavailable' })),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    await expect(queryClient.infiniteQuery(listQueryOptions(api.fetchClient, 'entity'))).rejects.toThrow(
      '503 Service Unavailable',
    );
  });
});
