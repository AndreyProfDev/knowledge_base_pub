import { useSuspenseQuery } from '@tanstack/react-query';
import { createFileRoute } from '@tanstack/react-router';

import { ErrorDialog } from '@/components/ErrorDialog';
import { KindForm } from '@/components/KindForm';
import { PageHeader } from '@/components/PageHeader';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { kindsQuery, payloadSchema } from '@/lib/kinds';

export const Route = createFileRoute('/$kind/$id/edit')({
  loader: ({ context: { queryClient, $api }, params: { kind, id } }) =>
    queryClient.query(
      $api.queryOptions('get', '/memory/{kind}/{item_id}', { params: { path: { kind, item_id: id } } }),
    ),
  component: EditItem,
  pendingComponent: () => <Skeleton className="h-64 w-full max-w-2xl" />,
  errorComponent: (props) => <ErrorDialog {...props} component="Edit item" />,
});

function EditItem() {
  const { kind, id } = Route.useParams();
  const { $api } = Route.useRouteContext();
  const schema = payloadSchema(useSuspenseQuery(kindsQuery($api)).data, kind);
  const { data: item } = $api.useSuspenseQuery('get', '/memory/{kind}/{item_id}', {
    params: { path: { kind, item_id: id } },
  });

  return (
    <>
      <PageHeader title={`Edit ${kind}`} back={{ kind }} />
      <Card className="w-full max-w-2xl">
        <CardContent>
          {/* Keyed: a param change keeps this route mounted, and the last item's save must not carry over. */}
          <KindForm key={item.id} kind={kind} schema={schema} item={item} />
        </CardContent>
      </Card>
    </>
  );
}
