import type { CustomStatusPanelProps } from 'ag-grid-react';

import { Button } from '@/components/ui/button';
import type { Paging } from '@/lib/grid-status';

function PanelButton({ label, busy, onClick }: Readonly<{ label: string; busy: boolean; onClick: () => unknown }>) {
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={busy}
      onClick={() => {
        void onClick();
      }}
    >
      {label}
    </Button>
  );
}

// A button, not onBodyScrollEnd: under autoHeight the grid body never scrolls.
export function LoadMorePanel({
  hasNextPage,
  isFetching,
  fetchNextPage,
  loadError,
  retry,
}: Readonly<CustomStatusPanelProps & Paging>) {
  if (loadError !== null) {
    return (
      <div className="flex items-center gap-3 py-1.5 text-sm text-destructive">
        <span role="alert">Load failed: {loadError}</span>
        <PanelButton label="Retry" busy={isFetching} onClick={retry} />
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3 py-1.5 text-sm text-muted-foreground">
      {hasNextPage ? (
        <>
          <span>more available</span>
          <PanelButton label="Load more" busy={isFetching} onClick={fetchNextPage} />
        </>
      ) : (
        <span>all loaded</span>
      )}
    </div>
  );
}
