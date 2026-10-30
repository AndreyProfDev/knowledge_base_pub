import type { QueryClient } from '@tanstack/react-query';
import { createRouter, type RouterHistory } from '@tanstack/react-router';

import type { Api } from './lib/api';
import { parseSearch, stringifySearch } from './lib/search-params';
import { routeTree } from './routeTree.gen';

export interface RouterContext {
  queryClient: QueryClient;
  $api: Api['$api'];
  fetchClient: Api['fetchClient'];
}

export function createAppRouter({ history, ...context }: RouterContext & { history?: RouterHistory }) {
  return createRouter({
    routeTree,
    context,
    ...(history ? { history } : {}),
    defaultPreload: 'intent',
    parseSearch,
    stringifySearch,
  });
}

export type AppRouter = ReturnType<typeof createAppRouter>;

declare module '@tanstack/react-router' {
  interface Register {
    router: AppRouter;
  }
}
