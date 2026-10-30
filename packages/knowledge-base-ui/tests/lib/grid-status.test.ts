import { describe, expect, it } from 'vitest';

import { pagingOf, statusBarFor } from '@/lib/grid-status';

function LoadMore(): null {
  return null;
}

const fetchNextPage = () => 'next';
const refetch = () => 'all';
const ok = {
  hasNextPage: true,
  isFetching: false,
  isFetchNextPageError: false,
  isRefetchError: false,
  error: null,
  fetchNextPage,
  refetch,
};

describe('pagingOf', () => {
  it('carries no error while every fetch succeeds', () => {
    expect(pagingOf(ok)).toEqual({
      hasNextPage: true,
      isFetching: false,
      fetchNextPage,
      loadError: null,
      retry: refetch,
    });
  });

  it('carries a failed next page, retried by fetching that page', () => {
    const paging = pagingOf({ ...ok, isFetchNextPageError: true, error: new Error('503 down') });
    expect(paging).toMatchObject({ loadError: '503 down', retry: fetchNextPage });
  });

  it('carries a failed refetch, retried by refetching', () => {
    const paging = pagingOf({ ...ok, isRefetchError: true, error: new Error('502 Bad Gateway') });
    expect(paging).toMatchObject({ loadError: '502 Bad Gateway', retry: refetch });
  });
});

describe('statusBarFor', () => {
  it('puts the row count left and the panel, given the paging, right', () => {
    const paging = pagingOf(ok);
    expect(statusBarFor(paging, LoadMore)).toEqual({
      statusPanels: [
        { statusPanel: 'agTotalAndFilteredRowCountComponent', align: 'left' },
        { statusPanel: LoadMore, align: 'right', statusPanelParams: paging },
      ],
    });
  });
});
