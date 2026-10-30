import type { CustomCellRendererProps } from 'ag-grid-react';
import { Ellipsis, Pencil, Trash2 } from 'lucide-react';
import { createContext, use } from 'react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type { MemoryItem } from '@/lib/api';

export interface RowActions {
  edit: (item: MemoryItem) => void;
  confirmDelete: (item: MemoryItem) => void;
  isLocked: (item: MemoryItem) => boolean;
}

// React context, not the grid's `context`: a cell re-renders when the lock it reads changes.
export const RowActionsContext = createContext<RowActions | undefined>(undefined);

export function ItemActions({ data }: Readonly<CustomCellRendererProps<MemoryItem>>) {
  const actions = use(RowActionsContext);
  if (!actions) throw new Error('ItemActions must be rendered within RowActionsContext');
  if (!data) return null;
  return (
    <div className="flex h-full items-center justify-end">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon">
            <Ellipsis />
            <span className="sr-only">Open menu</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            disabled={actions.isLocked(data)}
            onSelect={() => {
              actions.edit(data);
            }}
          >
            <Pencil />
            Edit
          </DropdownMenuItem>
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => {
              actions.confirmDelete(data);
            }}
          >
            <Trash2 />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
