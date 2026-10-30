import { describe, expect, it } from 'vitest';

import { isEditLocked, type Pending, pendingReducer, writtenIds } from '@/lib/pending';

const edit: Pending = { requestId: 'r1', kind: 'knowledge', itemIds: ['old-id', 'new-key-id'], action: 'save' };
const add: Pending = { requestId: 'r2', kind: 'entity', itemIds: ['new-id'], action: 'save' };

describe('pendingReducer', () => {
  it('adds a request once', () => {
    expect(
      pendingReducer(pendingReducer([edit], { type: 'add', pending: add }), { type: 'add', pending: add }),
    ).toEqual([edit, add]);
  });

  it('ends a request, leaving the rest', () => {
    expect(pendingReducer([edit, add], { type: 'end', requestId: 'r1' })).toEqual([add]);
  });
});

describe('writtenIds', () => {
  it("is an add's answered id, or an edit's path id when its key is unchanged", () => {
    expect(writtenIds(undefined, 'new-id')).toEqual(['new-id']);
    expect(writtenIds('same-id', 'same-id')).toEqual(['same-id']);
  });

  it("is both rows of a key-changing edit: the old one and its new key's", () => {
    expect(writtenIds('old-id', 'new-key-id')).toEqual(['old-id', 'new-key-id']);
  });
});

describe('isEditLocked', () => {
  it('locks every item a queued request writes', () => {
    expect(isEditLocked([edit], 'old-id')).toBe(true);
    expect(isEditLocked([edit], 'new-key-id')).toBe(true);
    expect(isEditLocked([edit], 'new-id')).toBe(false);
  });
});
