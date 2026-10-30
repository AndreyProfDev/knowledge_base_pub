import { describe, expect, it } from 'vitest';

import { ApiError, type RequestState } from '@/lib/api';
import { endOf, pollInterval, pollUntil } from '@/lib/requests';

const queued = { request_id: 'r', status: 'queued' } as const;
const done = { request_id: 'r', status: 'done' } as const;
const failed = { request_id: 'r', status: 'failed', error: 'over the token limit' } as const;

describe('requests', () => {
  it('polls until the request ends', () => {
    expect(pollInterval({ state: { error: null } })).toBe(1000);
    expect(pollInterval({ state: { data: queued, error: null } })).toBe(1000);
    expect(pollInterval({ state: { data: done, error: null } })).toBe(false);
    expect(pollInterval({ state: { data: failed, error: null } })).toBe(false);
  });

  it('stops polling once a poll fails, even over a queued state', () => {
    expect(pollInterval({ state: { error: 'down' } })).toBe(false);
    expect(pollInterval({ state: { data: queued, error: 'down' } })).toBe(false);
  });

  it('keeps polling over an error the caller does not stop on', () => {
    const poll = pollUntil<RequestState>(
      (data) => data.status !== 'queued',
      (error) => error === 'gone',
    );
    expect(poll({ state: { data: queued, error: 'down' } })).toBe(1000);
    expect(poll({ state: { error: 'gone' } })).toBe(false);
  });

  it('never restarts polling over settled data when a later refetch fails', () => {
    const poll = pollUntil<RequestState>(
      (data) => data.status !== 'queued',
      () => false,
    );
    expect(poll({ state: { data: done, error: 'down' } })).toBe(false);
  });

  it('toasts the end, not the queue', () => {
    expect(endOf(queued, null, 'save')).toBeNull();
    expect(endOf(done, null, 'save')).toEqual({ type: 'success', message: 'Saved' });
    expect(endOf(failed, null, 'save')).toEqual({
      type: 'error',
      message: 'Save failed',
      description: 'over the token limit',
    });
    expect(endOf({ request_id: 'r', status: 'failed', error: null }, null, 'save')).toEqual({
      type: 'error',
      message: 'Save failed',
      description: 'failed with no error recorded',
    });
  });

  it("names a delete's end as a delete, and its failure as the dump file left behind", () => {
    expect(endOf(done, null, 'delete')).toEqual({ type: 'success', message: 'Deleted' });
    expect(endOf(failed, null, 'delete')).toMatchObject({ message: 'Deleted, but its warm-up dump file remains' });
    expect(endOf(undefined, 'down', 'delete')).toMatchObject({ message: 'Delete status unknown' });
  });

  it("ends on the poll's failure, with its message, before any state", () => {
    const lost = new ApiError(404, '', { detail: 'Unknown request r' });
    expect(endOf(queued, lost, 'save')).toEqual({
      type: 'error',
      message: 'Save status unknown',
      description: '404 Unknown request r',
    });
    expect(endOf(undefined, { detail: 'raw' }, 'save')).toMatchObject({ description: '{"detail":"raw"}' });
    expect(endOf(undefined, 'down', 'save')).toMatchObject({ description: 'down' });
    expect(endOf(undefined, null, 'save')).toBeNull();
  });
});
