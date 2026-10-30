import { useQueryClient } from '@tanstack/react-query';
import { createFileRoute } from '@tanstack/react-router';
import { CircleAlert } from 'lucide-react';
import { useEffect } from 'react';
import { toast } from 'sonner';

import { ErrorDialog } from '@/components/ErrorDialog';
import { PageHeader } from '@/components/PageHeader';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { WarmupProgressView } from '@/components/WarmupProgressView';
import { WarmupPostError, WarmupReportTable } from '@/components/WarmupResult';
import { errorMessage, type WarmupProgress } from '@/lib/api';
import { memoryListsKey } from '@/lib/list-query';
import { pollUntil } from '@/lib/requests';
import { adminSearchSchema } from '@/lib/search-params';
import { notFoundDetail, warmupErrorRows } from '@/lib/warmup';

export const Route = createFileRoute('/admin')({
  validateSearch: adminSearchSchema,
  component: Admin,
  errorComponent: (props) => <ErrorDialog {...props} component="Admin" />,
});

const isUnknownRun = (error: unknown) => notFoundDetail(error) !== undefined;
// A failed poll (the API restarting mid-run) keeps polling; only the run's end or an unknown run stops it.
const warmupPollInterval = pollUntil<WarmupProgress>((data) => data.finished, isUnknownRun);
// A stale `?run=` answers 404 at once instead of after the default retries' backoff.
const retryUnlessUnknown = (failures: number, error: unknown) => !isUnknownRun(error) && failures < 3;

function useWarmupProgress(run: string | undefined) {
  const { $api } = Route.useRouteContext();
  const queryClient = useQueryClient();
  const query = $api.useQuery(
    'get',
    '/warmup/{run_id}',
    { params: { path: { run_id: run ?? '' } } },
    { enabled: run !== undefined, refetchInterval: warmupPollInterval, retry: retryUnlessUnknown },
  );
  const finished = query.data?.finished === true;
  useEffect(() => {
    if (finished) void queryClient.invalidateQueries({ queryKey: memoryListsKey });
  }, [finished, queryClient]);
  // A run forgotten mid-run (404 after data) drops its stale bar.
  const unknown = isUnknownRun(query.error);
  return {
    data: unknown ? undefined : query.data,
    error: query.error,
    running: run !== undefined && !unknown && !finished,
  };
}

function Admin() {
  const { run } = Route.useSearch();
  const navigate = Route.useNavigate();
  const { $api } = Route.useRouteContext();
  const progress = useWarmupProgress(run);
  // Shown inline by WarmupPostError; anything else is a toast, as other mutations do.
  const warmup = $api.useMutation('post', '/warmup', {
    onSuccess: (report) => navigate({ search: { run: report.run_id } }),
    onError: (error: unknown) => {
      if (!warmupErrorRows(error) && !notFoundDetail(error)) {
        toast.error('Warm-up failed', { description: errorMessage(error) });
      }
    },
  });

  return (
    <>
      <PageHeader title="Admin" />
      <Card className="w-full max-w-3xl">
        <CardHeader>
          <CardTitle>Warm-up</CardTitle>
          <CardDescription>
            Loads items from the configured warm-up directory; unchanged items are skipped.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div>
            <Button
              disabled={warmup.isPending || progress.running}
              onClick={() => {
                warmup.mutate({});
              }}
            >
              {warmup.isPending ? 'Validating files…' : 'Run warm-up'}
            </Button>
          </div>
          <WarmupPostError error={warmup.error} />
          {warmup.data && warmup.data.run_id === run ? <WarmupReportTable report={warmup.data} /> : null}
          {progress.data ? <WarmupProgressView progress={progress.data} /> : null}
          {progress.error ? <ProgressError error={progress.error} /> : null}
        </CardContent>
      </Card>
    </>
  );
}

// A stale `?run=` is not an error dialog: the run is simply gone.
function ProgressError({ error }: Readonly<{ error: unknown }>) {
  const text = notFoundDetail(error) ? 'This warm-up run is not known' : `Progress unknown: ${errorMessage(error)}`;
  return (
    <Alert variant="destructive">
      <CircleAlert />
      <AlertDescription>
        <p>{text}</p>
      </AlertDescription>
    </Alert>
  );
}
