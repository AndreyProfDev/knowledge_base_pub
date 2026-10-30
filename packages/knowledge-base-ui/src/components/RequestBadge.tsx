import { Badge } from '@/components/ui/badge';
import type { RequestState } from '@/lib/api';

const variants = { queued: 'secondary', done: 'default', failed: 'destructive' } as const;

export function RequestBadge({ status }: Readonly<{ status: RequestState['status'] }>) {
  return <Badge variant={variants[status]}>{status}</Badge>;
}
