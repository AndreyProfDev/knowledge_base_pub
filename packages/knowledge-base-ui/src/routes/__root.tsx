import { useSuspenseQuery } from '@tanstack/react-query';
import { createRootRouteWithContext, Link, Outlet } from '@tanstack/react-router';

import { ErrorDialog } from '@/components/ErrorDialog';
import { NavigationBar } from '@/components/NavigationBar';
import { PendingRequests } from '@/components/PendingRequests';
import { ThemeProvider } from '@/components/theme-provider';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Toaster } from '@/components/ui/sonner';
import { kindNames, kindsQuery } from '@/lib/kinds';
import type { RouterContext } from '@/router';

export const Route = createRootRouteWithContext<RouterContext>()({
  loader: ({ context: { queryClient, $api } }) => queryClient.query(kindsQuery($api)),
  component: RootLayout,
  notFoundComponent: NoSuchKind,
  errorComponent: (props) => <ErrorDialog {...props} component="Knowledge Base" />,
});

function useKindNames(): string[] {
  const { $api } = Route.useRouteContext();
  return kindNames(useSuspenseQuery(kindsQuery($api)).data);
}

function RootLayout() {
  const kinds = useKindNames();
  return (
    <ThemeProvider>
      <PendingRequests>
        <div className="flex min-h-svh flex-col">
          <NavigationBar kinds={kinds} />
          <main className="flex flex-1 flex-col gap-4 p-4">
            <Outlet />
          </main>
        </div>
        <Toaster />
      </PendingRequests>
    </ThemeProvider>
  );
}

function NoSuchKind() {
  const kinds = useKindNames();
  return (
    <Card className="w-full max-w-xl">
      <CardHeader>
        <CardTitle>
          <h1>No such kind</h1>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex gap-4 text-sm">
          {kinds.map((kind) => (
            <li key={kind}>
              <Link to="/$kind" params={{ kind }} className="font-medium underline underline-offset-4">
                {kind}
              </Link>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
