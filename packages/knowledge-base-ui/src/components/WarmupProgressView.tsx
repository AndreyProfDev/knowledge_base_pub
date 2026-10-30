import { Link } from '@tanstack/react-router';

import { Progress } from '@/components/ui/progress';
import type { WarmupProgress } from '@/lib/api';
import { progressPercent, progressText } from '@/lib/warmup';

export function WarmupProgressView({ progress }: Readonly<{ progress: WarmupProgress }>) {
  const value = progressPercent(progress);
  return (
    <div className="grid gap-2">
      <Progress value={value} aria-label="Warm-up progress" />
      <p className="text-sm tabular-nums">{progressText(progress)}</p>
      {progress.finished ? null : (
        <p className="text-sm text-muted-foreground">
          A failing item is retried for up to ~2.5 minutes before it counts as failed.
        </p>
      )}
      {progress.finished && progress.failed > 0 ? <WarmupFailures progress={progress} /> : null}
    </div>
  );
}

function WarmupFailures({ progress }: Readonly<{ progress: WarmupProgress }>) {
  return (
    <>
      <table className="w-full text-left text-sm">
        <caption className="text-left font-medium">Failed writes</caption>
        <thead>
          <tr>
            <th className="pr-4">Kind</th>
            <th className="pr-4">Item id</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {progress.failures.map((failure) => (
            <tr key={failure.request_id}>
              <td className="pr-4">{failure.kind}</td>
              <td className="pr-4">
                <Link
                  to="/requests/$requestId"
                  params={{ requestId: failure.request_id }}
                  className="font-mono underline underline-offset-4"
                >
                  {failure.item_id}
                </Link>
              </td>
              <td>{failure.error}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {progress.failures_truncated ? <p className="text-sm text-muted-foreground">and more</p> : null}
    </>
  );
}
