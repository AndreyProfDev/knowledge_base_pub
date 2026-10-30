import type { RJSFSchema } from '@rjsf/utils';
import { useQueryClient } from '@tanstack/react-query';
import { useRouteContext } from '@tanstack/react-router';
import { toast } from 'sonner';

import { usePending } from '@/components/PendingRequests';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { errorMessage, type MemoryItem, type WriteAccepted } from '@/lib/api';
import { itemLabel } from '@/lib/kind-ui';
import { listQueryKey } from '@/lib/list-query';

// DELETE is applied at once, so it waits for this confirm; Cancel sends nothing. Its 202 request
// removes the warm-up dump file, and is tracked so a failure there is shown.
export function DeleteItemDialog({
  kind,
  schema,
  item,
  onClose,
}: Readonly<{ kind: string; schema: RJSFSchema; item: MemoryItem; onClose: () => void }>) {
  const { $api } = useRouteContext({ from: '__root__' });
  const queryClient = useQueryClient();
  const { track } = usePending();
  const remove = $api.useMutation('delete', '/memory/{kind}/{item_id}', {
    onSuccess: (accepted: WriteAccepted) => {
      track({ requestId: accepted.request_id, kind, itemIds: [], action: 'delete' });
    },
    // Not "failed": a 500 can mean the item is gone but its dump removal was not queued; the
    // detail says which.
    onError: (error: unknown) => toast.error('Delete returned an error', { description: errorMessage(error) }),
    // Settled, not success: a 404 means another tab already deleted it.
    onSettled: () => queryClient.invalidateQueries({ queryKey: listQueryKey(kind) }),
  });

  return (
    <AlertDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this {kind}?</AlertDialogTitle>
          <AlertDialogDescription>
            <strong>{itemLabel(schema, item)}</strong> is deleted at once; nothing can undo it.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={() => {
              remove.mutate({ params: { path: { kind, item_id: item.id } } });
            }}
          >
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
