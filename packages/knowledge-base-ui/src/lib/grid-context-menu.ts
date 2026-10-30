import type { GetContextMenuItems } from 'ag-grid-community';

import type { MemoryItem } from './api';

// The row menu's two items on right-click; `[]` off a row (header, empty space) opens no menu.
export function contextMenuFor(o: {
  edit: (item: MemoryItem) => void;
  confirmDelete: (item: MemoryItem) => void;
  isLocked: (item: MemoryItem) => boolean;
}): GetContextMenuItems<MemoryItem> {
  return ({ node }) => {
    const item = node?.data;
    if (!item) return [];
    return [
      {
        name: 'Edit',
        disabled: o.isLocked(item),
        action: () => {
          o.edit(item);
        },
      },
      {
        name: 'Delete',
        cssClasses: ['text-destructive'],
        action: () => {
          o.confirmDelete(item);
        },
      },
    ];
  };
}
