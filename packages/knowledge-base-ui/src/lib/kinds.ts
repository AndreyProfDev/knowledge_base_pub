import type { RJSFSchema } from '@rjsf/utils';

import type { Api, KindSchema } from './api';

// Kinds are installed packages, fixed for a running API.
export function kindsQuery($api: Api['$api']) {
  return $api.queryOptions('get', '/kinds', {}, { staleTime: 'static' });
}

export function kindNames(kinds: readonly KindSchema[]): string[] {
  return kinds.map((k) => k.name);
}

export function kindTitle(kind: string): string {
  return kind.charAt(0).toUpperCase() + kind.slice(1);
}

export class UnknownKindError extends Error {
  constructor(kind: string, kinds: readonly KindSchema[]) {
    super(`Unknown kind "${kind}"; /kinds lists ${JSON.stringify(kindNames(kinds))}`);
    this.name = 'UnknownKindError';
  }
}

// `$kind` routes 404 an unknown kind before rendering, so reaching this with one is a bug, not an empty form.
export function payloadSchema(kinds: readonly KindSchema[], kind: string): RJSFSchema {
  const schema = kinds.find((k) => k.name === kind)?.payload_schema;
  if (schema === undefined) throw new UnknownKindError(kind, kinds);
  return schema;
}
