import type { RJSFSchema } from '@rjsf/utils';
import type { GetRowIdParams, GridReadyEvent } from 'ag-grid-community';
import { AgGridProvider, AgGridReact } from 'ag-grid-react';
import { useCallback, useMemo } from 'react';

import { ItemActions, type RowActions, RowActionsContext } from '@/components/ItemActions';
import { LoadMorePanel } from '@/components/LoadMorePanel';
import { AddItemButton } from '@/components/PageHeader';
import { usePending } from '@/components/PendingRequests';
import { useTheme } from '@/components/theme-provider';
import { Card, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import type { MemoryItem } from '@/lib/api';
import { contextMenuFor } from '@/lib/grid-context-menu';
import { gridModules, licenceProps } from '@/lib/grid-modules';
import { type Paging, statusBarFor } from '@/lib/grid-status';
import { gridThemeFor } from '@/lib/grid-theme';
import { columnsFor } from '@/lib/kind-ui';
import { kindTitle } from '@/lib/kinds';
import { isEditLocked } from '@/lib/pending';

// No column sorts or filters unless columnsFor opts it in.
const defaultColDef = { sortable: false, resizable: false, suppressMovable: true, filter: false };
const now = () => new Date();
const rowId = ({ data }: GetRowIdParams<MemoryItem>) => data.id;

// AgGridReact re-applies every prop whose identity changes, so each derived one is memoised.
export function ItemGrid({
  kind,
  schema,
  rows,
  paging: { hasNextPage, isFetching, fetchNextPage, loadError, retry },
  edit,
  confirmDelete,
}: Readonly<{
  kind: string;
  schema: RJSFSchema;
  rows: MemoryItem[];
  paging: Paging;
  edit: RowActions['edit'];
  confirmDelete: RowActions['confirmDelete'];
}>) {
  const { actualTheme } = useTheme();
  const { pending } = usePending();
  const theme = useMemo(() => gridThemeFor(actualTheme), [actualTheme]);
  const columnDefs = useMemo(
    () => columnsFor(schema, { complete: !hasNextPage, actions: ItemActions, now }),
    [schema, hasNextPage],
  );
  const statusBar = useMemo(
    () => statusBarFor({ hasNextPage, isFetching, fetchNextPage, loadError, retry }, LoadMorePanel),
    [hasNextPage, isFetching, fetchNextPage, loadError, retry],
  );
  const actions = useMemo(
    () => ({ edit, confirmDelete, isLocked: (item: MemoryItem) => isEditLocked(pending, item.id) }),
    [edit, confirmDelete, pending],
  );
  const contextMenu = useMemo(() => contextMenuFor(actions), [actions]);
  const label = useCallback(
    ({ api }: GridReadyEvent<MemoryItem>) => {
      api.setGridAriaProperty('label', kindTitle(kind));
    },
    [kind],
  );

  // No overlay module is registered: an empty list is this card, not a grid.
  if (rows.length === 0) {
    return (
      <Card className="w-full max-w-xl">
        <CardHeader>
          <CardTitle>No {kind} items yet.</CardTitle>
        </CardHeader>
        <CardFooter>
          <AddItemButton kind={kind} />
        </CardFooter>
      </Card>
    );
  }
  return (
    <RowActionsContext value={actions}>
      <AgGridProvider modules={gridModules} {...licenceProps(import.meta.env.VITE_AG_GRID_LICENSE_KEY)}>
        <AgGridReact<MemoryItem>
          defaultColDef={defaultColDef}
          domLayout="autoHeight"
          tooltipShowDelay={300}
          theme={theme}
          rowData={rows}
          columnDefs={columnDefs}
          statusBar={statusBar}
          getContextMenuItems={contextMenu}
          getRowId={rowId}
          ensureDomOrder
          suppressColumnVirtualisation
          onGridReady={label}
        />
      </AgGridProvider>
    </RowActionsContext>
  );
}
