import createFetchClient, { type Middleware } from 'openapi-fetch';
import createQueryClient from 'openapi-react-query';

import type { components, paths } from '@/api/schema';

export type KindSchema = components['schemas']['KindSchema'];
export type MemoryItem = components['schemas']['MemoryItem'];
export type RequestState = components['schemas']['RequestState'];
export type WriteAccepted = components['schemas']['WriteAccepted'];
export type MemoryHit = components['schemas']['MemoryHit'];
export type WarmupReport = components['schemas']['WarmupReport'];
export type WarmupProgress = components['schemas']['WarmupProgress'];

function messageFor(status: number, statusText: string, body: unknown): string {
  if (typeof body === 'object' && body !== null) {
    const detail = 'detail' in body ? body.detail : undefined;
    return `${String(status)} ${typeof detail === 'string' ? detail : JSON.stringify(body)}`;
  }
  const text = typeof body === 'string' && body ? body : statusText || 'with no body';
  return `${String(status)} ${text}`;
}

// Every non-2xx response; `body` is the parsed JSON (a 422's `detail` list), the text, or undefined.
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, statusText: string, body: unknown) {
    super(messageFor(status, statusText, body));
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

// A 422's `detail`, each entry naming a field's `loc` and its `msg`; undefined for any other error.
export function validationDetails(error: ApiError): components['schemas']['ValidationError'][] | undefined {
  const { body } = error;
  if (error.status !== 422 || typeof body !== 'object' || body === null || !('detail' in body)) return undefined;
  return Array.isArray(body.detail) ? (body.detail as components['schemas']['ValidationError'][]) : undefined;
}

// A thrown non-Error (a raw response body) keeps its fields rather than reading "[object Object]".
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return typeof error === 'object' &&
    // Stryker disable next-line ConditionalExpression: equivalent: null reads "null" through JSON.stringify and String alike
    error !== null
    ? JSON.stringify(error)
    : String(error);
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.clone().text();
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

// openapi-fetch resolves a body-less error with `error: undefined`, which openapi-react-query takes for success.
const throwOnError: Middleware = {
  async onResponse({ response }) {
    if (!response.ok) throw new ApiError(response.status, response.statusText, await parseBody(response));
    return undefined;
  },
};

// The relative `/api` nginx proxies; tests pass a fake `fetch`.
export function createApi(fetch?: (input: Request) => Promise<Response>) {
  const fetchClient = createFetchClient<paths>({ baseUrl: '/api', ...(fetch ? { fetch } : {}) });
  fetchClient.use(throwOnError);
  return { fetchClient, $api: createQueryClient(fetchClient) };
}

export type Api = ReturnType<typeof createApi>;
