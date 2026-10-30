import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { ApiError, createApi } from '@/lib/api';

describe('createApi', () => {
  it('sends every call through the given fetch, under /api', async () => {
    const seen: Request[] = [];
    const { fetchClient, $api } = createApi((req) => {
      seen.push(req);
      return Promise.resolve(Response.json([{ name: 'entity', payload_schema: {} }]));
    });

    const { data } = await fetchClient.GET('/kinds');
    const cached = await new QueryClient().query($api.queryOptions('get', '/kinds'));

    expect(data).toEqual([{ name: 'entity', payload_schema: {} }]);
    expect(cached).toEqual(data);
    expect(seen.map((req) => new URL(req.url).pathname)).toEqual(['/api/kinds', '/api/kinds']);
  });

  it.each([
    [new Response(null, { status: 404 }), '404 with no body', undefined],
    [new Response('', { status: 502, statusText: 'Bad Gateway' }), '502 Bad Gateway', undefined],
    [new Response('upstream down', { status: 503 }), '503 upstream down', 'upstream down'],
    [Response.json({ detail: 'Unknown kind' }, { status: 404 }), '404 Unknown kind', { detail: 'Unknown kind' }],
    [Response.json({ code: 7 }, { status: 500 }), '500 {"code":7}', { code: 7 }],
    // A JSON scalar is no text to show: the status text stands in.
    [Response.json(42, { status: 500, statusText: 'Server Error' }), '500 Server Error', 42],
  ])('rejects a non-2xx response as ApiError: %#', async (response, message, body) => {
    const { $api } = createApi(() => Promise.resolve(response));
    const query = new QueryClient().query($api.queryOptions('get', '/kinds'));

    await expect(query).rejects.toThrow(ApiError);
    await expect(query).rejects.toMatchObject({ name: 'ApiError', message, status: response.status, body });
  });

  it('rejects a bodiless DELETE failure instead of resolving it', async () => {
    const { fetchClient } = createApi(() => Promise.resolve(new Response(null, { status: 404 })));

    await expect(
      fetchClient.DELETE('/memory/{kind}/{item_id}', { params: { path: { kind: 'entity', item_id: 'x' } } }),
    ).rejects.toThrow('404 with no body');
  });

  it('builds a client without a fetch', () => {
    expect(createApi().fetchClient.GET).toBeTypeOf('function');
  });
});
