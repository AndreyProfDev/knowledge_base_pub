import { errorMessage, type RequestState } from './api';

const POLL_MS = 1000;

// By default a failed poll (an unknown id, the API down) stops it: retrying cannot learn the status.
export function pollUntil<T>(settled: (data: T) => boolean, isFatal: (error: unknown) => boolean = () => true) {
  return (query: { state: { data?: T | undefined; error?: unknown } }): number | false => {
    const { data, error } = query.state;
    // Settled data stays settled: a later refetch failing (window focus, remount) never restarts polling.
    const done = data !== undefined && settled(data);
    return done || (Boolean(error) && isFatal(error)) ? false : POLL_MS;
  };
}

export const pollInterval = pollUntil<RequestState>((data) => data.status !== 'queued');

/** A delete's request removes the item's warm-up dump file; the store delete already happened. */
export type RequestAction = 'save' | 'delete';

export const requestWords = {
  save: { pending: 'Saving', done: 'Saved', failed: 'Save failed', unknown: 'Save status unknown' },
  delete: {
    pending: 'Deleting',
    done: 'Deleted',
    failed: 'Deleted, but its warm-up dump file remains',
    unknown: 'Delete status unknown',
  },
} as const;

type End = { type: 'success'; message: string } | { type: 'error'; message: string; description: string };

// How a tracked request ends: its terminal state, or the poll's own failure.
export function endOf(data: RequestState | undefined, error: unknown, action: RequestAction): End | null {
  const words = requestWords[action];
  if (error) return { type: 'error', message: words.unknown, description: errorMessage(error) };
  switch (data?.status) {
    case 'done':
      return { type: 'success', message: words.done };
    case 'failed':
      return { type: 'error', message: words.failed, description: data.error ?? 'failed with no error recorded' };
    default:
      return null;
  }
}
