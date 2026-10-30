import { describe, expect, it } from 'vitest';

import { adminSearchSchema, parseSearch, searchQuery, searchSchema, stringifySearch } from '@/lib/search-params';

describe('searchSchema', () => {
  it('passes valid params through', () => {
    expect(searchSchema.parse({ q: 'tea', kind: 'entity', top_k: 5, min_score: 0.3 })).toEqual({
      q: 'tea',
      kind: 'entity',
      top_k: 5,
      min_score: 0.3,
    });
  });

  it('maps "all" to no kind', () => {
    expect(searchSchema.parse({ q: 'tea', kind: 'all' })).toEqual({ q: 'tea' });
  });

  it.each([
    [{ q: 3 }, 'q'],
    [{ q: 'tea', top_k: 0 }, 'top_k'],
    [{ q: 'tea', top_k: 1.5 }, 'top_k'],
    [{ q: 'tea', top_k: 1001 }, 'top_k'],
    [{ q: 'tea', top_k: '5' }, 'top_k'],
    [{ q: 'tea', min_score: 'x' }, 'min_score'],
    [{ q: 'tea', min_score: Infinity }, 'min_score'],
    [{ q: ['tea'] }, 'q'],
    [{ q: 'tea', kind: true }, 'kind'],
  ])('fails on a malformed value instead of dropping it: %o', (params, param) => {
    const result = searchSchema.safeParse(params);
    expect(result.success).toBe(false);
    expect(result.error?.issues.map((i) => i.path)).toEqual([[param]]);
  });

  it('defaults q to empty', () => {
    expect(searchSchema.parse({})).toEqual({ q: '' });
  });
});

describe('parseSearch', () => {
  it('keeps text params as typed and JSON-parses only the numeric ones', () => {
    expect(parseSearch('?q=true&kind=null&top_k=5&min_score=0.25')).toEqual({
      q: 'true',
      kind: 'null',
      top_k: 5,
      min_score: 0.25,
    });
    expect(parseSearch('q=1.50')).toEqual({ q: '1.50' });
  });

  it('leaves a non-JSON numeric param a string, for the schema to reject', () => {
    expect(parseSearch('?q=tea&top_k=five')).toEqual({ q: 'tea', top_k: 'five' });
  });

  it('keeps a repeated key as a list, for the schema to reject', () => {
    expect(parseSearch('?q=a&q=b&top_k=5&top_k=6')).toEqual({ q: ['a', 'b'], top_k: ['5', '6'] });
    // Joined, these would read as the JSON list [1,2].
    expect(parseSearch('?top_k=%5B1&top_k=2%5D')).toEqual({ top_k: ['[1', '2]'] });
  });

  it('round-trips what stringifySearch writes', () => {
    const search = { q: '[1]', kind: 'entity', top_k: 3, min_score: 0.4 };
    const url = stringifySearch(search);
    expect(url).toBe('?q=%5B1%5D&kind=entity&top_k=3&min_score=0.4');
    expect(parseSearch(url)).toEqual(search);
  });
});

describe('adminSearchSchema', () => {
  it('takes an optional run id and rejects a repeated one', () => {
    expect(adminSearchSchema.parse({})).toEqual({});
    expect(adminSearchSchema.parse(parseSearch('?run=1e5'))).toEqual({ run: '1e5' });
    expect(adminSearchSchema.safeParse(parseSearch('?run=a&run=b')).success).toBe(false);
  });
});

describe('searchQuery', () => {
  it('sends an unset param as null, which openapi-fetch leaves out', () => {
    expect(searchQuery({ q: 'tea', kind: undefined })).toEqual({
      params: { query: { q: 'tea', kind: null, top_k: null, min_score: null } },
    });
    expect(searchQuery({ q: 'tea', kind: 'entity', top_k: 5, min_score: 0.3 })).toEqual({
      params: { query: { q: 'tea', kind: 'entity', top_k: 5, min_score: 0.3 } },
    });
  });
});
