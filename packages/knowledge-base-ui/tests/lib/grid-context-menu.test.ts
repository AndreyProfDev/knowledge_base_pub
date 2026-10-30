import type { GetContextMenuItemsParams, IRowNode, MenuItemDef } from 'ag-grid-community';
import { describe, expect, it } from 'vitest';

import type { MemoryItem } from '@/lib/api';
import { contextMenuFor } from '@/lib/grid-context-menu';

const item: MemoryItem = { id: 'a1', kind: 'entity', updated_at: '2026-10-17T00:00:00Z', payload: {} };

function menuFor(locked: boolean, node: Partial<IRowNode<MemoryItem>> | null) {
  const calls: string[] = [];
  const menu = contextMenuFor({
    edit: (i) => calls.push(`edit ${i.id}`),
    confirmDelete: (i) => calls.push(`delete ${i.id}`),
    isLocked: () => locked,
  });
  const items = menu({ node } as GetContextMenuItemsParams<MemoryItem>) as MenuItemDef[];
  return { calls, items };
}

describe('contextMenuFor', () => {
  it("offers Edit and Delete for the clicked row's item", () => {
    const { calls, items } = menuFor(false, { data: item });

    expect(items.map((i) => [i.name, i.disabled, i.cssClasses])).toEqual([
      ['Edit', false, undefined],
      ['Delete', undefined, ['text-destructive']],
    ]);
    for (const i of items) i.action?.({} as never);
    expect(calls).toEqual(['edit a1', 'delete a1']);
  });

  it('disables Edit while the item is locked', () => {
    expect(menuFor(true, { data: item }).items[0]?.disabled).toBe(true);
  });

  it('opens no menu off a row', () => {
    expect(menuFor(false, null).items).toEqual([]);
    expect(menuFor(false, {}).items).toEqual([]);
  });
});
