import { createFileRoute, notFound, redirect } from '@tanstack/react-router';

import { kindsQuery } from '@/lib/kinds';

// `throw: true` throws from inside the call, so lint's only-throw-error stays on.
export const Route = createFileRoute('/')({
  loader: async ({ context: { queryClient, $api } }) => {
    const [first] = await queryClient.query(kindsQuery($api));
    if (!first) notFound({ throw: true });
    else redirect({ to: '/$kind', params: { kind: first.name }, throw: true });
  },
});
