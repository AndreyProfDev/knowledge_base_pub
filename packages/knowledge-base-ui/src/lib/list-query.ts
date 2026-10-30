import { infiniteQueryOptions } from '@tanstack/react-query';

import type { Api } from './api';

const PAGE_SIZE = 50;

// Keyed as openapi-react-query keys `GET /memory/{kind}`; invalidating this prefix hits every kind.
export const memoryListsKey = ['get', '/memory/{kind}'] as const;

export function listQueryKey(kind: string) {
  return [...memoryListsKey, { params: { path: { kind } } }] as const;
}

export function listQueryOptions(fetchClient: Api['fetchClient'], kind: string) {
  return infiniteQueryOptions({
    queryKey: listQueryKey(kind),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam, signal }) => {
      // A non-2xx response throws ApiError from createApi's middleware.
      const { data, response } = await fetchClient.GET('/memory/{kind}', {
        params: { path: { kind }, query: { limit: PAGE_SIZE, cursor: pageParam } },
        signal,
      });
      if (data === undefined) throw new Error(`${String(response.status)} page with no body`);
      return data;
    },
    getNextPageParam: (page) => page.next_cursor,
  });
}
