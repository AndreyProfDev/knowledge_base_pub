import type { GridOptions } from 'ag-grid-community';
import type { CustomStatusPanelProps } from 'ag-grid-react';
import type { ComponentType } from 'react';

import { errorMessage } from './api';

export interface Paging {
  hasNextPage: boolean;
  // Any fetch, not only the next page's: fetchNextPage cancels a running refetch, keeping its stale pages.
  isFetching: boolean;
  fetchNextPage: () => unknown;
  // Set once rows are shown: a suspense query throws only its first load.
  loadError: string | null;
  retry: () => unknown;
}

interface InfiniteQueryState {
  hasNextPage: boolean;
  isFetching: boolean;
  isFetchNextPageError: boolean;
  isRefetchError: boolean;
  error: unknown;
  fetchNextPage: () => unknown;
  refetch: () => unknown;
}

// A failed next page retries that page; a failed refetch (after an invalidate) refetches every page.
export function pagingOf(query: InfiniteQueryState): Paging {
  const failed = query.isFetchNextPageError || query.isRefetchError;
  return {
    hasNextPage: query.hasNextPage,
    isFetching: query.isFetching,
    fetchNextPage: query.fetchNextPage,
    loadError: failed ? errorMessage(query.error) : null,
    retry: query.isFetchNextPageError ? query.fetchNextPage : query.refetch,
  };
}

// The row count left, the Load more panel right, reading `paging` from its `statusPanelParams`.
export function statusBarFor(
  paging: Paging,
  panel: ComponentType<CustomStatusPanelProps & Paging>,
): NonNullable<GridOptions['statusBar']> {
  return {
    statusPanels: [
      { statusPanel: 'agTotalAndFilteredRowCountComponent', align: 'left' },
      { statusPanel: panel, align: 'right', statusPanelParams: paging },
    ],
  };
}
