import { type APIRequestContext, expect, test as base } from '@playwright/test';

import { isTrialBanner } from '../src/lib/ag-grid-banner';

// The no-key AG Grid trial banner is the one expected console error.
export const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on('console', (message) => {
        if (message.type() === 'error' && !isTrialBanner(message.text()))
          errors.push(`${message.text()} (${message.location().url})`);
      });
      page.on('pageerror', (error) => errors.push(error.message));
      await use(errors);
      expect(errors).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

// Polls a request until it leaves `queued`, then asserts it finished cleanly.
async function settled(request: APIRequestContext, requestId: string): Promise<void> {
  let state: { status: string; error?: string | null } = { status: 'queued' };
  await expect
    .poll(async () => {
      state = (await (await request.get(`/api/requests/${requestId}`)).json()) as typeof state;
      return state.status;
    })
    .not.toBe('queued');
  expect(state).toEqual({ request_id: requestId, status: 'done', error: null });
}

// Stores through the API and waits for the worker, so a test starts from a listed item.
export async function store(
  request: APIRequestContext,
  kind: string,
  payload: object,
): Promise<{ itemId: string; requestId: string }> {
  const response = await request.post(`/api/memory/${kind}`, { data: payload });
  expect(response.status()).toBe(202);
  const { request_id, item_id } = (await response.json()) as { request_id: string; item_id: string };
  await settled(request, request_id);
  return { itemId: item_id, requestId: request_id };
}

// Deletes through the API and waits for the dump-file removal; a `failed` one fails with its error.
export async function remove(request: APIRequestContext, kind: string, itemId: string): Promise<void> {
  const response = await request.delete(`/api/memory/${kind}/${itemId}`);
  expect(response.status()).toBe(202);
  const { request_id } = (await response.json()) as { request_id: string };
  await settled(request, request_id);
}
