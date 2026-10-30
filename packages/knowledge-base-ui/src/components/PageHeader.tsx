import { Link } from '@tanstack/react-router';
import { Plus } from 'lucide-react';
import type { ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import { kindTitle } from '@/lib/kinds';

export function AddItemButton({ kind }: Readonly<{ kind: string }>) {
  return (
    <Button asChild>
      <Link to="/$kind/new" params={{ kind }}>
        <Plus />
        Add {kind}
      </Link>
    </Button>
  );
}

export function PageHeader({
  title,
  back,
  action,
}: Readonly<{ title: string; back?: { kind: string }; action?: ReactNode }>) {
  return (
    <div className="flex flex-col gap-1">
      {back ? (
        <Button variant="ghost" size="sm" className="self-start" asChild>
          <Link to="/$kind" params={{ kind: back.kind }}>
            ← {kindTitle(back.kind)}
          </Link>
        </Button>
      ) : null}
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {action}
      </div>
    </div>
  );
}
