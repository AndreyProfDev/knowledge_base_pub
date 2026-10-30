import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router';
import { act, render } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';

import { createApi } from '@/lib/api';
import { createAppRouter } from '@/router';
import { routeTree } from '@/routeTree.gen';

import type { FakeApi } from './fake-api';

type AnyRoute = typeof routeTree | { options: object; children?: unknown };
const SPLIT = ['component', 'errorComponent', 'pendingComponent', 'notFoundComponent'] as const;

// autoCodeSplitting makes each route component a lazy chunk, imported on its first render inside a test's
// 5 s budget; under `make -j` that cold import ran past it. Imported here, it is the file's import time.
function preloadAll(route: AnyRoute): Promise<void>[] {
  const options = route.options as Partial<Record<(typeof SPLIT)[number], { preload?: () => Promise<void> }>>;
  const children = Object.values((route.children ?? {}) as Record<string, AnyRoute>);
  return [...SPLIT.flatMap((key) => options[key]?.preload?.() ?? []), ...children.flatMap(preloadAll)];
}
await Promise.all(preloadAll(routeTree));

// The app's own router over a memory history and the fake transport; loaded before the first render.
export async function renderRoute(
  path: string,
  api: FakeApi,
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  const router = createAppRouter({
    queryClient,
    ...createApi(api.fetch),
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  // A shown pending component otherwise holds for 500 ms of real time, e.g. after an error's Retry.
  router.update({ ...router.options, defaultPendingMinMs: 0 });
  await act(() => router.load());
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, user, queryClient };
}
