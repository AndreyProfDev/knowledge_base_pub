import { join } from 'node:path';

import tailwindcss from '@tailwindcss/vite';
import { tanstackRouter } from '@tanstack/router-plugin/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

import { isTrialBanner } from './src/lib/ag-grid-banner.ts';

export default defineConfig({
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: { alias: { '@': join(import.meta.dirname, 'src') } },
  // As nginx does: /api/x -> knowledge-api's /x.
  server: {
    proxy: { '/api': { target: 'http://localhost:8000', rewrite: (path) => path.replace(/^\/api/, '') } },
  },
  test: {
    environment: 'jsdom',
    // e2e/*.spec.ts are Playwright's.
    include: ['tests/**/*.test.{ts,tsx}'],
    setupFiles: ['tests/setup.ts'],
    coverage: { provider: 'v8', include: ['src/lib/**'], thresholds: { 100: true } },
    onConsoleLog: (log) => !isTrialBanner(log),
  },
});
