import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';

import { expect, remove, store, test } from './fixtures';

const RUN = Date.now().toString(36);

// One of each kind, so the lists render a grid and edit and request status have an item.
const seeds = {
  entity: { name: `Axe ${RUN}`, type: 'tool', description: 'Accessibility engine' },
  knowledge: { category: 'fact', content: `Axe scans every route ${RUN}` },
  workflow: { name: `Audit ${RUN}`, description: '', steps: ['Scan', 'Fix'] },
};

const routes: { name: string; path: string; ready: (page: Page) => Promise<void> }[] = [];
const stored: { kind: string; itemId: string }[] = [];
const heading = (name: string) => (page: Page) => expect(page.getByRole('heading', { name })).toBeVisible();
const grid = (page: Page) => expect(page.getByRole('grid')).toBeVisible();

test.beforeAll(async ({ request }) => {
  for (const [kind, payload] of Object.entries(seeds)) {
    const { itemId, requestId } = await store(request, kind, payload);
    stored.push({ kind, itemId });
    routes.push(
      { name: `/${kind}`, path: `/${kind}`, ready: grid },
      { name: `/${kind}/new`, path: `/${kind}/new`, ready: heading(`Add ${kind}`) },
      { name: `/${kind}/$id/edit`, path: `/${kind}/${itemId}/edit`, ready: heading(`Edit ${kind}`) },
      {
        name: `/requests/$requestId (${kind})`,
        path: `/requests/${requestId}`,
        ready: (page) => expect(page.getByText('done')).toBeVisible(),
      },
    );
  }
  routes.push(
    { name: '/', path: '/', ready: grid },
    { name: '/search', path: '/search', ready: (page) => expect(page.getByRole('search')).toBeVisible() },
    {
      name: '/search?q',
      path: `/search?q=${encodeURIComponent(seeds.knowledge.content)}`,
      ready: (page) => expect(page.getByRole('progressbar').first()).toBeVisible(),
    },
    {
      name: '/admin',
      path: '/admin',
      ready: (page) => expect(page.getByRole('button', { name: 'Run warm-up' })).toBeEnabled(),
    },
    { name: 'not found', path: '/recipes', ready: (page) => expect(page.getByText('No such kind')).toBeVisible() },
  );
});

// Each seed is dumped into the warm-up dir; kb.spec's warm-up tests expect only its 2.
test.afterAll(async ({ request }) => {
  for (const { kind, itemId } of stored) await remove(request, kind, itemId);
});

for (const colorScheme of ['light', 'dark'] as const) {
  test(`every route passes axe in ${colorScheme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme });
    const found: string[] = [];
    for (const route of routes) {
      await page.goto(route.path);
      await route.ready(page);
      await expect(page.locator('html')).toHaveClass(colorScheme);
      // The theme class lands after first paint; scanning mid-transition measures blended colours.
      await page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished)));
      const { violations } = await new AxeBuilder({ page }).analyze();
      for (const { id, nodes } of violations) {
        found.push(`${route.name}: ${id} at ${nodes.map((n) => n.target.join(' ')).join(', ')}`);
      }
    }
    expect(found).toEqual([]);
  });
}
