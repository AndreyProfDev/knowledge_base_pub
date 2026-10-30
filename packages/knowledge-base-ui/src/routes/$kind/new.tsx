import { useSuspenseQuery } from '@tanstack/react-query';
import { createFileRoute } from '@tanstack/react-router';

import { KindForm } from '@/components/KindForm';
import { PageHeader } from '@/components/PageHeader';
import { Card, CardContent } from '@/components/ui/card';
import { kindsQuery, payloadSchema } from '@/lib/kinds';

export const Route = createFileRoute('/$kind/new')({
  component: AddItem,
});

function AddItem() {
  const { kind } = Route.useParams();
  const { $api } = Route.useRouteContext();
  const schema = payloadSchema(useSuspenseQuery(kindsQuery($api)).data, kind);

  return (
    <>
      <PageHeader title={`Add ${kind}`} back={{ kind }} />
      <Card className="w-full max-w-2xl">
        <CardContent>
          <KindForm kind={kind} schema={schema} />
        </CardContent>
      </Card>
    </>
  );
}
