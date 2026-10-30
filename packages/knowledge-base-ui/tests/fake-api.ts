import type { MemoryItem } from '@/lib/api';

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';
type Handler = (req: Request) => Response | Promise<Response>;

// Keyed by method + pathname without `/api` or the query; anything unmatched answers 404.
export function fakeApi(handlers: Partial<Record<`${Method} ${string}`, Handler>>) {
  const requests: Request[] = [];
  const fetch = async (req: Request): Promise<Response> => {
    requests.push(req.clone());
    const path = new URL(req.url).pathname.replace(/^\/api/, '');
    const handler = handlers[`${req.method as Method} ${path}`];
    return handler ? handler(req) : new Response(null, { status: 404 });
  };
  return { fetch, requests };
}

export type FakeApi = ReturnType<typeof fakeApi>;

export const kinds = [
  {
    name: 'knowledge',
    payload_schema: {
      title: 'KnowledgePayload',
      type: 'object',
      properties: {
        category: { title: 'Category', type: 'string', enum: ['fact', 'preference', 'constraint', 'goal'] },
        content: { title: 'Content', type: 'string', 'x-long-text': true },
      },
    },
    max_chars: 500,
  },
  { name: 'entity', payload_schema: { title: 'EntityPayload', type: 'object', properties: {} }, max_chars: 500 },
];

// Ids sort as their number does, as the API's id order would.
export function fact(n: number): MemoryItem {
  return {
    id: `k${String(n).padStart(4, '0')}-0000-0000`,
    kind: 'knowledge',
    updated_at: '2026-10-17T10:00:00Z',
    payload: { category: 'fact', content: `Fact ${String(n)}` },
  };
}

export function facts(from: number, to: number): MemoryItem[] {
  return Array.from({ length: to - from }, (_, i) => fact(from + i));
}

// `fact(1)`'s DELETE 202, and its dump-removal request `d1` answered `status`.
export const deleted = () =>
  Response.json({ request_id: 'd1', item_id: fact(1).id, status: 'queued' }, { status: 202 });
export const deleteRequest = (status: 'done' | 'failed', error: string | null = null) =>
  Response.json({ request_id: 'd1', status, error });

export const page = (items: MemoryItem[], next_cursor: string | null = null) => Response.json({ items, next_cursor });
