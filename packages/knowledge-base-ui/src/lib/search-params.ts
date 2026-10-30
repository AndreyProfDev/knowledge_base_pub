import { stringifySearchWith } from '@tanstack/react-router';
import { z } from 'zod';

const NUMERIC = ['top_k', 'min_score'];

// Only the numeric params are JSON: the router's default would read `?q=true` as a boolean and `?q=1.50` as 1.5.
// A repeated key stays a list, which searchSchema rejects, rather than its last value winning.
export function parseSearch(searchStr: string): Record<string, unknown> {
  const params = new URLSearchParams(searchStr);
  const query: Record<string, unknown> = Object.fromEntries(
    [...new Set(params.keys())].map((key) => {
      const values = params.getAll(key);
      return [key, values.length === 1 ? values[0] : values];
    }),
  );
  for (const key of NUMERIC) {
    const value = query[key];
    if (typeof value !== 'string') continue;
    try {
      query[key] = JSON.parse(value);
    } catch {
      // Left a string, which searchSchema rejects.
    }
  }
  return query;
}

// Strings unquoted, the inverse of parseSearch.
export const stringifySearch = stringifySearchWith(JSON.stringify);

// A malformed value fails the route (its ErrorDialog names the param) rather than searching without it.
export const searchSchema = z.object({
  // `.default` makes `q` optional to a link, so a plain `/search` needs no `search` prop.
  q: z.string().default(''),
  // "All kinds" carries `all`: Radix Select.Item rejects an empty value.
  kind: z
    .string()
    .optional()
    .transform((kind) => (kind === 'all' ? undefined : kind)),
  top_k: z.number().int().min(1).max(1000).optional(),
  // zod 4's number() already rejects Infinity.
  min_score: z.number().optional(),
});

export type SearchParams = z.output<typeof searchSchema>;

// `run` is a warm-up run_id, so a reload resumes its progress.
export const adminSearchSchema = z.object({ run: z.string().optional() });

// The API's query, one shape for the loader and the component; openapi-fetch skips the nulls.
export function searchQuery({ q, kind, top_k, min_score }: SearchParams) {
  return { params: { query: { q, kind: kind ?? null, top_k: top_k ?? null, min_score: min_score ?? null } } };
}
