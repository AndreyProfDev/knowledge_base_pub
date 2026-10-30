import { createFileRoute } from '@tanstack/react-router';
import { CircleAlert } from 'lucide-react';

import { PageHeader } from '@/components/PageHeader';
import { RequestBadge } from '@/components/RequestBadge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { errorMessage } from '@/lib/api';
import { pollInterval } from '@/lib/requests';

export const Route = createFileRoute('/requests/$requestId')({
  component: RequestStatus,
});

function RequestStatus() {
  const { requestId } = Route.useParams();
  const { $api } = Route.useRouteContext();
  const { data, error } = $api.useQuery(
    'get',
    '/requests/{request_id}',
    { params: { path: { request_id: requestId } } },
    { refetchInterval: pollInterval },
  );
  // A failed poll stops polling, so a last-known status would read as current.
  const problem = error ? `Status unknown: ${errorMessage(error)}` : data?.error;

  return (
    <>
      <PageHeader title="Request" />
      <Card className="w-full max-w-xl">
        <CardHeader>
          <CardTitle>
            <code className="font-mono text-sm font-normal">{requestId}</code>
          </CardTitle>
          {data && !error ? (
            <CardAction>
              <RequestBadge status={data.status} />
            </CardAction>
          ) : null}
        </CardHeader>
        {problem ? (
          <CardContent>
            <Alert variant="destructive">
              <CircleAlert />
              <AlertDescription>
                <p>{problem}</p>
              </AlertDescription>
            </Alert>
          </CardContent>
        ) : null}
      </Card>
    </>
  );
}
