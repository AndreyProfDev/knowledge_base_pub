import { describe, expect, it } from 'vitest';

import { ApiError, type WarmupProgress } from '@/lib/api';
import { notFoundDetail, progressPercent, progressText, warmupErrorRows } from '@/lib/warmup';

function progress(fields: Partial<WarmupProgress>): WarmupProgress {
  const p = {
    run_id: 'r',
    total: 4,
    done: 0,
    failed: 0,
    unchanged: 0,
    failures: [],
    failures_truncated: false,
    ...fields,
  };
  const pending = p.total - p.done - p.failed;
  return { pending, finished: pending === 0, ...p };
}

describe('progressPercent', () => {
  it('counts failed writes as finished with', () => {
    expect(progressPercent(progress({ done: 1 }))).toBe(25);
    expect(progressPercent(progress({ done: 1, failed: 1 }))).toBe(50);
    expect(progressPercent(progress({ done: 2, failed: 2 }))).toBe(100);
    expect(progressPercent(progress({ total: 3, done: 1 }))).toBe(33);
  });

  it('is short of full while one write is pending', () => {
    expect(progressPercent(progress({ total: 400, done: 399 }))).toBe(99);
  });

  it('is full when nothing was queued', () => {
    expect(progressPercent(progress({ total: 0, unchanged: 7 }))).toBe(100);
  });
});

describe('progressText', () => {
  it('names the written, failed and unchanged counts', () => {
    expect(progressText(progress({ done: 2, failed: 1, unchanged: 5 }))).toBe(
      '3 of 4 written · 1 failed · 5 unchanged',
    );
  });

  it('says nothing was written when nothing was queued', () => {
    expect(progressText(progress({ total: 0, unchanged: 2 }))).toBe('Nothing to write: all 2 items unchanged');
  });
});

describe('notFoundDetail', () => {
  it("returns a 404's detail text and nothing for any other error", () => {
    expect(notFoundDetail(new ApiError(404, '', { detail: 'warm-up directory /x does not exist' }))).toBe(
      'warm-up directory /x does not exist',
    );
    expect(notFoundDetail(new ApiError(404, 'Not Found', undefined))).toBe('404 Not Found');
    expect(notFoundDetail(new ApiError(404, 'Not Found', null))).toBe('404 Not Found');
    expect(notFoundDetail(new ApiError(404, '', { detail: ['x'] }))).toBe('404 {"detail":["x"]}');
    expect(notFoundDetail(new ApiError(500, '', { detail: 'down' }))).toBeUndefined();
    expect(notFoundDetail(new Error('offline'))).toBeUndefined();
  });
});

describe('warmupErrorRows', () => {
  it('maps each detail entry to a row, leaving missing loc parts empty', () => {
    const body = {
      detail: [
        { type: 'warmup_item_invalid', loc: ['a.yaml', 'fake', 0, 'title'], msg: 'Field required', ctx: {} },
        { type: 'warmup_item_invalid', loc: ['b.yaml', 'recipe'], msg: 'unknown kind' },
        { type: 'warmup_item_invalid', loc: ['c.yaml'], msg: 'bad YAML' },
        { type: 'warmup_item_invalid', loc: ['d.yaml', 'workflow', 2, 'steps', 1], msg: 'blank' },
        {},
      ],
    };
    expect(warmupErrorRows(new ApiError(422, '', body))).toEqual([
      { file: 'a.yaml', kind: 'fake', index: '0', msg: 'title: Field required' },
      { file: 'b.yaml', kind: 'recipe', index: '', msg: 'unknown kind' },
      { file: 'c.yaml', kind: '', index: '', msg: 'bad YAML' },
      { file: 'd.yaml', kind: 'workflow', index: '2', msg: 'steps.1: blank' },
      { file: '', kind: '', index: '', msg: '' },
    ]);
  });

  it('is undefined for anything but a 422 detail list', () => {
    expect(warmupErrorRows(new ApiError(422, '', { detail: 'x' }))).toBeUndefined();
    expect(warmupErrorRows(new ApiError(422, '', 'text'))).toBeUndefined();
    expect(warmupErrorRows(new ApiError(422, '', null))).toBeUndefined();
    expect(warmupErrorRows(new ApiError(422, '', {}))).toBeUndefined();
    expect(warmupErrorRows(new ApiError(404, '', { detail: [] }))).toBeUndefined();
    expect(warmupErrorRows(new Error('offline'))).toBeUndefined();
  });
});
