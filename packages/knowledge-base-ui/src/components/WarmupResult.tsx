import { CircleAlert } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import type { WarmupReport } from '@/lib/api';
import { notFoundDetail, warmupErrorRows } from '@/lib/warmup';

export function WarmupReportTable({ report }: Readonly<{ report: WarmupReport }>) {
  return (
    <>
      <table className="w-full text-left text-sm tabular-nums">
        <caption className="text-left font-medium">{report.total_queued} queued</caption>
        <thead>
          <tr>
            <th className="pr-4">Kind</th>
            <th className="pr-4">Queued</th>
            <th>Unchanged</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(report.kinds).map(([kind, counts]) => (
            <tr key={kind}>
              <td className="pr-4">{kind}</td>
              <td className="pr-4">{counts.queued}</td>
              <td>{counts.unchanged}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <WarmupShadowed report={report} />
    </>
  );
}

// Hand-written copies that differ from the dump copy queued in their place.
function WarmupShadowed({ report }: Readonly<{ report: WarmupReport }>) {
  if (report.shadowed.length === 0) return null;
  return (
    <Alert>
      <CircleAlert />
      <AlertDescription>
        <p>These hand-written items differ from their dump copies; the dump copies were used.</p>
        <table className="w-full text-left text-sm">
          <thead>
            <tr>
              <th className="pr-4">Hand-written</th>
              <th>Dump</th>
            </tr>
          </thead>
          <tbody>
            {report.shadowed.map((shadow) => (
              <tr key={shadow.hand_written}>
                <td className="pr-4">{shadow.hand_written}</td>
                <td>{shadow.dump}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </AlertDescription>
    </Alert>
  );
}

// The POST failures the user fixes in the files: a 422's every row, or the missing directory.
export function WarmupPostError({ error }: Readonly<{ error: unknown }>) {
  const rows = warmupErrorRows(error);
  const missing = notFoundDetail(error);
  if (!rows && !missing) return null;
  return (
    <Alert variant="destructive">
      <CircleAlert />
      <AlertDescription>
        {rows ? (
          <>
            <p>The warm-up files are invalid; nothing was queued.</p>
            <table className="w-full text-left text-sm">
              <thead>
                <tr>
                  <th className="pr-4">File</th>
                  <th className="pr-4">Kind</th>
                  <th className="pr-4">Index</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.file}|${row.kind}|${row.index}|${row.msg}`}>
                    <td className="pr-4">{row.file}</td>
                    <td className="pr-4">{row.kind}</td>
                    <td className="pr-4">{row.index}</td>
                    <td>{row.msg}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p>{missing}</p>
        )}
      </AlertDescription>
    </Alert>
  );
}
