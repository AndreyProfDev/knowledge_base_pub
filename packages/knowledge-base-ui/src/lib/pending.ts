import type { RequestAction } from './requests';

/** A queued write; `itemIds` are every id it writes: an edit's path id and the id answered for its key. */
export interface Pending {
  requestId: string;
  kind: string;
  itemIds: readonly string[];
  action: RequestAction;
}

export type PendingAction = { type: 'add'; pending: Pending } | { type: 'end'; requestId: string };

export function pendingReducer(state: readonly Pending[], action: PendingAction): Pending[] {
  switch (action.type) {
    case 'add':
      return [...state.filter((p) => p.requestId !== action.pending.requestId), action.pending];
    case 'end':
      return state.filter((p) => p.requestId !== action.requestId);
  }
}

// A key-changing edit (`pathId` ≠ `answeredId`) writes both rows.
export function writtenIds(pathId: string | undefined, answeredId: string): string[] {
  return pathId === undefined || pathId === answeredId ? [answeredId] : [pathId, answeredId];
}

export function isEditLocked(pending: readonly Pending[], itemId: string): boolean {
  return pending.some((p) => p.itemIds.includes(itemId));
}
