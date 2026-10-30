import type { components } from '@/api/schema';

import { ApiError, validationDetails, type WarmupProgress } from './api';

// Failed writes are written too: the bar measures what the worker has finished with.
// Floored: 100 only once every write is, never while one is pending.
export function progressPercent({ done, failed, total }: WarmupProgress): number {
  return total === 0 ? 100 : Math.floor(((done + failed) / total) * 100);
}

export function progressText({ done, failed, total, unchanged }: WarmupProgress): string {
  if (total === 0) return `Nothing to write: all ${String(unchanged)} items unchanged`;
  return `${String(done + failed)} of ${String(total)} written · ${String(failed)} failed · ${String(unchanged)} unchanged`;
}

// The API's text for a 404 (it names the missing directory or the unknown run).
export function notFoundDetail(error: unknown): string | undefined {
  if (!(error instanceof ApiError) || error.status !== 404) return undefined;
  const body: unknown = error.body;
  return typeof body === 'object' && body !== null && 'detail' in body && typeof body.detail === 'string'
    ? body.detail
    : error.message;
}

function locPart(loc: (string | number)[] | undefined, index: number): string {
  return String(loc?.[index] ?? '');
}

// A warm-up 422's `loc` is (file, kind, index, ...field); a YAML error stops at file, a bad kind at kind.
// The field path prefixes the message: "Field required" alone does not say which field.
export function warmupErrorRows(error: unknown) {
  const details = error instanceof ApiError ? validationDetails(error) : undefined;
  if (!details) return undefined;
  return details.map((detail: Partial<components['schemas']['ValidationError']>) => {
    const field = detail.loc?.slice(3).join('.') ?? '';
    const msg = detail.msg ?? '';
    return {
      file: locPart(detail.loc, 0),
      kind: locPart(detail.loc, 1),
      index: locPart(detail.loc, 2),
      msg: field ? `${field}: ${msg}` : msg,
    };
  });
}
