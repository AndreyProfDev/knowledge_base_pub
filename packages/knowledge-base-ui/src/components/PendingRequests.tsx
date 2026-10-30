import { useQueryClient } from '@tanstack/react-query';
import { useNavigate, useRouteContext } from '@tanstack/react-router';
import { createContext, type ReactNode, use, useCallback, useEffect, useMemo, useReducer } from 'react';
import { toast } from 'sonner';

import { listQueryKey } from '@/lib/list-query';
import { type Pending, pendingReducer } from '@/lib/pending';
import { endOf, pollInterval, requestWords } from '@/lib/requests';

interface PendingState {
  pending: readonly Pending[];
  track: (pending: Pending) => void;
}

const PendingContext = createContext<PendingState | undefined>(undefined);

// One poller per request, so a request outlives the form that started it.
function PendingPoll({ pending, onEnd }: Readonly<{ pending: Pending; onEnd: (requestId: string) => void }>) {
  const { $api } = useRouteContext({ from: '__root__' });
  const queryClient = useQueryClient();
  const { data, error } = $api.useQuery(
    'get',
    '/requests/{request_id}',
    { params: { path: { request_id: pending.requestId } } },
    { refetchInterval: pollInterval },
  );

  useEffect(() => {
    const end = endOf(data, error, pending.action);
    if (!end) return;
    if (end.type === 'success') toast.success(end.message);
    else toast.error(end.message, { description: end.description });
    void queryClient.invalidateQueries({ queryKey: listQueryKey(pending.kind) });
    // An edit form opened while locked holds the pre-write GET: it unlocks only once that is refetched.
    const refetches = pending.itemIds.map((itemId) => {
      const { queryKey } = $api.queryOptions('get', '/memory/{kind}/{item_id}', {
        params: { path: { kind: pending.kind, item_id: itemId } },
      });
      return queryClient.invalidateQueries({ queryKey });
    });
    void Promise.allSettled(refetches).finally(() => {
      onEnd(pending.requestId);
    });
  }, [$api, data, error, onEnd, pending, queryClient]);

  return null;
}

export function PendingRequests({ children }: Readonly<{ children: ReactNode }>) {
  const [pending, dispatch] = useReducer(pendingReducer, []);
  const navigate = useNavigate();

  const track = useCallback(
    (next: Pending) => {
      dispatch({ type: 'add', pending: next });
      toast.info(`${requestWords[next.action].pending} ${next.kind}…`, {
        action: {
          label: 'View status',
          onClick: () => {
            void navigate({ to: '/requests/$requestId', params: { requestId: next.requestId } });
          },
        },
      });
    },
    [navigate],
  );
  const end = useCallback((requestId: string) => {
    dispatch({ type: 'end', requestId });
  }, []);
  const value = useMemo(() => ({ pending, track }), [pending, track]);

  return (
    <PendingContext value={value}>
      {children}
      {pending.map((p) => (
        <PendingPoll key={p.requestId} pending={p} onEnd={end} />
      ))}
    </PendingContext>
  );
}

export function usePending(): PendingState {
  const context = use(PendingContext);
  if (!context) throw new Error('usePending must be used within PendingRequests');
  return context;
}
