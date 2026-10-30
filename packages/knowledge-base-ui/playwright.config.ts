import { defineConfig, devices } from '@playwright/test';

// Against the compose stack `make ui-e2e` starts; writes go through the real queue and embedder.
// `make ui-e2e` sets KB_UI_URL to its own stack's port, so it runs beside the one on 8081.
// No default: the specs write and delete memories, and any guess would be the prod stack.
// globalSetup refuses a run without it; the config itself must still load for knip.
const baseURL = process.env['KB_UI_URL'] ?? '';

export default defineConfig({
  testDir: 'e2e',
  globalSetup: './e2e/require-ui-url.ts',
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: 'list',
  expect: { timeout: 15_000 },
  use: { baseURL, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
