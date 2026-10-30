import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { createApi } from '@/lib/api';
import { kindNames, kindsQuery, kindTitle, payloadSchema, UnknownKindError } from '@/lib/kinds';

const kinds = [
  { name: 'knowledge', payload_schema: { title: 'KnowledgePayload' }, max_chars: 500 },
  { name: 'entity', payload_schema: { title: 'EntityPayload' }, max_chars: 500 },
];

describe('kinds', () => {
  it('lists the names in API order', () => {
    expect(kindNames(kinds)).toEqual(['knowledge', 'entity']);
  });

  it('capitalises the kind name', () => {
    expect(kindTitle('knowledge')).toBe('Knowledge');
  });

  it('queries GET /kinds once for a running API', async () => {
    const seen: string[] = [];
    const { $api } = createApi((req) => {
      seen.push(new URL(req.url).pathname);
      return Promise.resolve(Response.json(kinds));
    });
    const queryClient = new QueryClient();

    expect(await queryClient.query(kindsQuery($api))).toEqual(kinds);
    await queryClient.query(kindsQuery($api));
    expect(seen).toEqual(['/api/kinds']);
    expect(kindsQuery($api).staleTime).toBe('static');
  });

  it("finds a kind's payload schema", () => {
    expect(payloadSchema(kinds, 'entity')).toEqual({ title: 'EntityPayload' });
  });

  it('throws on a kind /kinds does not list, naming it and the known ones', () => {
    expect(() => payloadSchema(kinds, 'recipes')).toThrow(UnknownKindError);
    expect(() => payloadSchema(kinds, 'recipes')).toThrow(expect.objectContaining({ name: 'UnknownKindError' }));
    expect(() => payloadSchema(kinds, 'recipes')).toThrow(
      `Unknown kind "recipes"; /kinds lists ${JSON.stringify(kindNames(kinds))}`,
    );
  });
});
