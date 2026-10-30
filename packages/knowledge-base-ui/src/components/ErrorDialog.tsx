import { type ErrorComponentProps, useRouter } from '@tanstack/react-router';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { errorMessage } from '@/lib/api';

const TITLE_MAX = 100;

// No query error reset: every suspense query is a loader's, so its error reaches here from the loader,
// and Retry's invalidate re-runs that loader, unmounting this dialog until it settles.
export function ErrorDialog({ component, error: thrown }: ErrorComponentProps & { component: string }) {
  const error = thrown instanceof Error ? thrown : new Error(errorMessage(thrown));
  const router = useRouter();
  const [open, setOpen] = useState(true);

  const retry = () => {
    void router.invalidate();
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="flex h-96 min-h-96 w-96 min-w-96 max-w-none resize flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>Error: {error.message.slice(0, TITLE_MAX)}</DialogTitle>
          <DialogDescription className="max-h-24 overflow-y-auto wrap-break-word">
            An error occurred in {component}: {error.message}
          </DialogDescription>
        </DialogHeader>
        <div className="grid flex-1 gap-4 overflow-hidden">
          <Textarea
            readOnly
            aria-label="Stack trace"
            className="h-full min-h-32 resize-none overflow-y-auto"
            value={error.stack ?? ''}
          />
        </div>
        <DialogFooter className="shrink-0">
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button onClick={retry}>Retry</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
