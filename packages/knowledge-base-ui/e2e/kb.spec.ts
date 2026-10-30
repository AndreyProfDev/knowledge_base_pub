import type { Page } from '@playwright/test';

import { expect, remove, store, test } from './fixtures';

const RUN = Date.now().toString(36);
const entity = {
  name: `Ada ${RUN}`,
  description: `Wrote the first program ${RUN}`,
  edited: `Wrote the first published program ${RUN}`,
};
const fact = { content: `Tea is green ${RUN}`, edited: `Green tea is unoxidised ${RUN}` };

test.describe.configure({ mode: 'serial' });

async function openRowMenu(page: Page, text: string) {
  await page.getByRole('row').filter({ hasText: text }).getByRole('button', { name: 'Open menu' }).click();
}

async function expectSaved(page: Page, kind: string) {
  await expect(page.getByText(`Saving ${kind}…`)).toBeVisible();
  await expect(page.getByText('Saved', { exact: true })).toBeVisible();
}

// A failed forget toasts "Deleted, but its warm-up dump file remains": exact match keeps it from passing.
async function expectDeleted(page: Page, kind: string) {
  await expect(page.getByText(`Deleting ${kind}…`)).toBeVisible();
  await expect(page.getByText('Deleted', { exact: true })).toBeVisible();
}

const cell = (page: Page, text: string) => page.getByRole('gridcell', { name: text, exact: true });

test('adds an entity: queued, then done, then listed', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Main' }).getByRole('link');
  await expect(nav).toHaveText(['Entity', 'Knowledge', 'Workflow', 'Search', 'Admin']);
  await nav.getByText('Entity').click();
  await page.getByRole('link', { name: 'Add entity' }).first().click();
  await page.getByLabel('Name').fill(entity.name);
  await page.getByRole('button', { name: 'Select type' }).click();
  await page.getByRole('option', { name: 'person' }).click();
  await page.getByLabel('Description').fill(entity.description);
  await page.getByRole('button', { name: 'Add', exact: true }).click();

  await expectSaved(page, 'entity');
  await expect(cell(page, entity.name)).toBeVisible();
  await expect(cell(page, entity.description)).toBeVisible();
});

test('edits the entity in place', async ({ page }) => {
  await page.goto('/entity');
  await openRowMenu(page, entity.name);
  await page.getByRole('menuitem', { name: 'Edit' }).click();
  await expect(page.getByRole('heading', { name: 'Edit entity' })).toBeVisible();
  await page.getByLabel('Description').fill(entity.edited);
  await page.getByRole('button', { name: 'Save' }).click();

  await expectSaved(page, 'entity');
  await expect(cell(page, entity.edited)).toBeVisible();
  await expect(cell(page, entity.description)).toHaveCount(0);
});

test('deletes from the row menu only once confirmed', async ({ page }) => {
  const deletes: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'DELETE') deletes.push(request.url());
  });
  await page.goto('/entity');

  await openRowMenu(page, entity.name);
  await page.getByRole('menuitem', { name: 'Delete' }).click();
  const dialog = page.getByRole('alertdialog', { name: 'Delete this entity?' });
  await expect(dialog).toContainText(entity.name);
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toBeHidden();
  expect(deletes).toEqual([]);
  await expect(cell(page, entity.name)).toBeVisible();

  await openRowMenu(page, entity.name);
  await page.getByRole('menuitem', { name: 'Delete' }).click();
  await dialog.getByRole('button', { name: 'Delete' }).click();
  await expectDeleted(page, 'entity');
  await expect(cell(page, entity.name)).toHaveCount(0);
  expect(deletes).toHaveLength(1);
});

test('a key-changing edit replaces the row', async ({ page }) => {
  await page.goto('/knowledge/new');
  await page.getByRole('button', { name: 'Select category' }).click();
  await page.getByRole('option', { name: 'fact' }).click();
  await page.getByLabel('Content').fill(fact.content);
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await expectSaved(page, 'knowledge');
  await expect(cell(page, fact.content)).toBeVisible();

  await openRowMenu(page, fact.content);
  await page.getByRole('menuitem', { name: 'Edit' }).click();
  await page.getByLabel('Content').fill(fact.edited);
  await page.getByRole('button', { name: 'Save' }).click();
  await expectSaved(page, 'knowledge');
  await expect(cell(page, fact.edited)).toBeVisible();
  await expect(cell(page, fact.content)).toHaveCount(0);
});

test('search shows the hit with its score', async ({ page }) => {
  await page.goto('/search');
  await page.getByLabel('Query').fill(fact.edited);
  await page.getByRole('button', { name: 'Search' }).click();

  await expect(page).toHaveURL(/[?&]q=/);
  const hit = page.locator('[data-slot="card"]').filter({ hasText: fact.edited }).first();
  await expect(hit).toContainText('knowledge');
  await expect(hit.getByRole('progressbar', { name: /^score \d\.\d\d$/ })).toBeVisible();
});

test('deletes from the right-click menu', async ({ page }) => {
  await page.goto('/knowledge');
  await cell(page, fact.edited).click({ button: 'right' });
  await page.locator('.ag-menu').getByText('Delete', { exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click();
  await expectDeleted(page, 'knowledge');
  await expect(cell(page, fact.edited)).toHaveCount(0);
});

// The Category column keeps its colId when `filter` turns false; the applied set filter must go with it.
test('drops the Category filter when a refetch makes the list incomplete again', async ({ page, request }) => {
  test.setTimeout(120_000);
  const stored = [
    await store(request, 'knowledge', { category: 'preference', content: `Filter pref ${RUN}` }),
    await store(request, 'knowledge', { category: 'fact', content: `Filter fact ${RUN}` }),
  ];
  await page.goto('/knowledge');
  await expect(page.getByText('all loaded')).toBeVisible();
  const count = page.getByRole('status').filter({ hasText: 'Rows' });
  await page.getByRole('columnheader', { name: 'Category' }).locator('.ag-header-cell-filter-button').click();
  await page.locator('.ag-set-filter-list').getByText('fact', { exact: true }).click();
  await expect(cell(page, `Filter fact ${RUN}`)).toHaveCount(0);
  await expect(count).toHaveText(/\bof\b/);

  stored.push(
    ...(await Promise.all(
      Array.from({ length: 50 }, (_, i) =>
        store(request, 'knowledge', { category: 'fact', content: `Filter ${RUN} ${String(i)}` }),
      ),
    )),
  );
  await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')));
  await expect(page.getByText('more available')).toBeVisible();
  await expect(count).toHaveText(/Rows\s*:\s*50\s*$/);
  // The next test's single Load more must reach "all loaded".
  for (const { itemId } of stored) await remove(request, 'knowledge', itemId);
});

test('pages with Load more until all loaded', async ({ page, request }) => {
  test.setTimeout(120_000);
  const stored = await Promise.all(
    Array.from({ length: 51 }, (_, i) =>
      store(request, 'knowledge', { category: 'fact', content: `Page ${RUN} ${String(i)}` }),
    ),
  );
  await page.goto('/knowledge');
  await expect(page.getByText('more available')).toBeVisible();
  const count = page.getByRole('status').filter({ hasText: 'Rows' });
  await expect(count).toHaveText(/Rows\s*:\s*50\s*$/);
  await page.getByRole('button', { name: 'Load more' }).click();
  await expect(page.getByText('all loaded')).toBeVisible();
  await expect(count).toHaveText(/Rows\s*:\s*(5[1-9]|[6-9]\d|\d{3,})\s*$/);
  // Each stored item is dumped into the warm-up dir; the warm-up tests expect only its 2.
  for (const { itemId } of stored) await remove(request, 'knowledge', itemId);
});

test('switches to dark and back', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.goto('/knowledge');
  const html = page.locator('html');
  await expect(html).toHaveClass('light');
  await page.getByRole('button', { name: 'Toggle theme' }).click();
  await page.getByRole('menuitem', { name: 'Dark' }).click();
  await expect(html).toHaveClass('dark');
  await page.reload();
  await expect(html).toHaveClass('dark');
});

test('serves index.html revalidated and redirects /api relative to the port', async ({ request }) => {
  for (const path of ['/', '/knowledge']) {
    expect((await request.get(path)).headers()['cache-control']).toBe('no-cache');
  }
  const bare = await request.get('/api', { maxRedirects: 0 });
  expect(bare.status()).toBe(301);
  expect(bare.headers()['location']).toBe('/api/');
});

test('refuses framing and sniffing on the index and on an asset', async ({ request }) => {
  const index = await request.get('/');
  const asset = /\/assets\/[^"]+\.js/.exec(await index.text())?.[0];
  expect(asset).toBeDefined();
  const assetResponse = await request.get(asset ?? '');
  expect(assetResponse.headers()['cache-control']).toBe('public, max-age=31536000, immutable');
  for (const response of [index, assetResponse]) {
    expect(response.headers()).toMatchObject({
      'x-frame-options': 'DENY',
      'content-security-policy': "frame-ancestors 'none'",
      'x-content-type-options': 'nosniff',
    });
  }
});

// Last: the Category-filter test counts rows, and these add e2e/warmup/knowledge.yaml's 2 items.
// `make ui-e2e` mounts a copy of e2e/warmup that the dump writes into: every earlier test removes what it stores.
const warmed = ['Warm-up seeds the knowledge base from YAML files.', 'Warm-up skips items already stored unchanged.'];

test('warm-up writes the fixture items and the bar reaches 100%', async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto('/admin');
  await page.getByRole('button', { name: 'Run warm-up' }).click();
  await expect(page).toHaveURL(/[?&]run=/);
  const bar = page.getByRole('progressbar', { name: 'Warm-up progress' });
  await expect(bar).toHaveAttribute('aria-valuenow', '100', { timeout: 90_000 });
  await expect(page.getByText(/2 of 2 written · 0 failed · 0 unchanged/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run warm-up' })).toBeEnabled();

  // Load every page (autoHeight renders every loaded row).
  await page.goto('/knowledge');
  const loadMore = page.getByRole('button', { name: 'Load more' });
  await expect(async () => {
    if ((await loadMore.isVisible()) && (await loadMore.isEnabled())) await loadMore.click({ timeout: 1000 });
    await expect(page.getByText('all loaded')).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 60_000 });
  for (const content of warmed) await expect(cell(page, content)).toBeVisible();
});

test('a second warm-up has nothing to write', async ({ page }) => {
  await page.goto('/admin');
  await page.getByRole('button', { name: 'Run warm-up' }).click();
  await expect(page.getByText('Nothing to write: all 2 items unchanged')).toBeVisible();
  await expect(page.getByRole('progressbar', { name: 'Warm-up progress' })).toHaveAttribute('aria-valuenow', '100');
});
