import { useSuspenseQuery } from '@tanstack/react-query';
import { createFileRoute } from '@tanstack/react-router';
import type { SubmitEvent } from 'react';

import { ErrorDialog } from '@/components/ErrorDialog';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import type { MemoryHit } from '@/lib/api';
import { payloadFields } from '@/lib/kind-ui';
import { kindNames, kindsQuery, payloadSchema } from '@/lib/kinds';
import { type SearchParams, searchQuery, searchSchema } from '@/lib/search-params';

export const Route = createFileRoute('/search')({
  validateSearch: searchSchema,
  loaderDeps: ({ search }) => search,
  loader: async ({ context: { queryClient, $api }, deps }) => {
    if (deps.q) await queryClient.query($api.queryOptions('get', '/search', searchQuery(deps)));
  },
  component: Search,
  pendingComponent: () => <Skeleton className="h-64 w-full max-w-3xl" />,
  errorComponent: (props) => <ErrorDialog {...props} component="Search" />,
});

function Search() {
  const search = Route.useSearch();
  return (
    <>
      <PageHeader title="Search" />
      {/* Remounted per search, so Back and reload show the URL's query in the form. */}
      <SearchForm key={JSON.stringify(search)} search={search} />
      {search.q ? <Hits search={search} /> : null}
    </>
  );
}

function numberOrUndefined(value: FormDataEntryValue | null): number | undefined {
  return typeof value === 'string' && value !== '' ? Number(value) : undefined;
}

function SearchForm({ search }: Readonly<{ search: SearchParams }>) {
  const navigate = Route.useNavigate();
  const { $api } = Route.useRouteContext();
  const kinds = kindNames(useSuspenseQuery(kindsQuery($api)).data);

  // The URL is the query: an empty field is the API's default, "All kinds" no kind.
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const q = data.get('q');
    const kind = data.get('kind');
    void navigate({
      search: {
        q: typeof q === 'string' ? q : '',
        kind: typeof kind === 'string' && kind !== 'all' ? kind : undefined,
        top_k: numberOrUndefined(data.get('top_k')),
        min_score: numberOrUndefined(data.get('min_score')),
      },
    });
  };

  return (
    <form className="flex flex-wrap items-end gap-4" role="search" onSubmit={submit}>
      <div className="grid gap-2">
        <Label htmlFor="q">Query</Label>
        <Input id="q" name="q" type="search" className="w-80" defaultValue={search.q} />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="kind">Kind</Label>
        <Select name="kind" defaultValue={search.kind ?? 'all'}>
          <SelectTrigger id="kind" className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All kinds</SelectItem>
            {kinds.map((kind) => (
              <SelectItem key={kind} value={kind}>
                {kind}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="top_k">Top k</Label>
        <Input id="top_k" name="top_k" type="number" min={1} max={1000} className="w-24" defaultValue={search.top_k} />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="min_score">Min score</Label>
        <Input
          id="min_score"
          name="min_score"
          type="number"
          step="any"
          className="w-24"
          defaultValue={search.min_score}
        />
      </div>
      <Button type="submit">Search</Button>
    </form>
  );
}

function Hits({ search }: Readonly<{ search: SearchParams }>) {
  const { $api } = Route.useRouteContext();
  const kinds = useSuspenseQuery(kindsQuery($api)).data;
  const { data: hits } = $api.useSuspenseQuery('get', '/search', searchQuery(search));

  if (hits.length === 0) return <p className="text-sm text-muted-foreground">No hits.</p>;
  return (
    <div className="flex max-w-3xl flex-col gap-3">
      {hits.map((hit) => (
        <Hit key={hit.id} hit={hit} fields={payloadFields(payloadSchema(kinds, hit.kind), hit.payload)} />
      ))}
    </div>
  );
}

function Hit({ hit, fields }: Readonly<{ hit: MemoryHit; fields: [string, string][] }>) {
  const score = hit.score.toFixed(2);
  const value = Math.min(1, Math.max(0, hit.score)) * 100;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <Badge variant="secondary">{hit.kind}</Badge>
        </CardTitle>
        <CardAction>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium tabular-nums">{score}</span>
            <Progress value={value} aria-label={`score ${score}`} className="w-24" />
          </div>
        </CardAction>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {fields.map(([title, text]) => (
            <div key={title} className="contents">
              <dt className="text-muted-foreground">{title}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
