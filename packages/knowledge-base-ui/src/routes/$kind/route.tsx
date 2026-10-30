import { createFileRoute, notFound } from '@tanstack/react-router';

import { kindNames, kindsQuery } from '@/lib/kinds';

// beforeLoad, not loader: child loaders run in parallel with a loader, so /recipes would GET /memory/recipes.
export const Route = createFileRoute('/$kind')({
  beforeLoad: async ({ context: { queryClient, $api }, params: { kind } }) => {
    const kinds = await queryClient.query(kindsQuery($api));
    if (!kindNames(kinds).includes(kind)) notFound({ throw: true });
  },
});
