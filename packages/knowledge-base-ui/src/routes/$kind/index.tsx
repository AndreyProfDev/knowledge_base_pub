import { useSuspenseInfiniteQuery, useSuspenseQuery } from '@tanstack/react-query';
import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { useCallback, useMemo, useState } from 'react';

import { DeleteItemDialog } from '@/components/DeleteItemDialog';
import { ErrorDialog } from '@/components/ErrorDialog';
import { ItemGrid } from '@/components/ItemGrid';
import { AddItemButton, PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/ui/skeleton';
import type { MemoryItem } from '@/lib/api';
import { pagingOf } from '@/lib/grid-status';
import { kindsQuery, kindTitle, payloadSchema } from '@/lib/kinds';
import { listQueryOptions } from '@/lib/list-query';

export const Route = createFileRoute('/$kind/')({
  // Fills an empty cache only: a refetch over cached rows is the observer's, so it fails into the panel.
  loader: ({ context: { queryClient, fetchClient }, params: { kind } }) =>
    queryClient.infiniteQuery({ ...listQueryOptions(fetchClient, kind), staleTime: 'static' }),
  component: ItemList,
  pendingComponent: () => <Skeleton className="h-64 w-full" />,
  errorComponent: (props) => <ErrorDialog {...props} component="Item list" />,
});

function ItemList() {
  const { kind } = Route.useParams();
  const { $api, fetchClient } = Route.useRouteContext();
  const schema = payloadSchema(useSuspenseQuery(kindsQuery($api)).data, kind);
  const query = useSuspenseInfiniteQuery(listQueryOptions(fetchClient, kind));
  const { data } = query;
  const rows = useMemo(() => data.pages.flatMap((page) => page.items), [data]);
  const [deleting, setDeleting] = useState<MemoryItem | null>(null);
  const navigate = useNavigate();
  const edit = useCallback(
    (item: MemoryItem) => {
      void navigate({ to: '/$kind/$id/edit', params: { kind, id: item.id } });
    },
    [navigate, kind],
  );

  return (
    <>
      <PageHeader title={kindTitle(kind)} action={<AddItemButton kind={kind} />} />
      <ItemGrid
        kind={kind}
        schema={schema}
        rows={rows}
        paging={pagingOf(query)}
        edit={edit}
        confirmDelete={setDeleting}
      />
      {deleting ? (
        <DeleteItemDialog
          kind={kind}
          schema={schema}
          item={deleting}
          onClose={() => {
            setDeleting(null);
          }}
        />
      ) : null}
    </>
  );
}
