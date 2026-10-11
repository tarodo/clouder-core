import { defineConfig } from 'vitest/config';
import { playwright } from '@vitest/browser-playwright';
import react from '@vitejs/plugin-react';
import path from 'node:path';

/**
 * Vitest browser-mode config — SEPARATE from the default jsdom run.
 *
 * Run with: pnpm test:browser
 * The default `pnpm test` (jsdom) intentionally excludes *.browser.test.tsx files.
 * This config intentionally includes ONLY *.browser.test.tsx files.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  test: {
    browser: {
      enabled: true,
      provider: playwright(),
      headless: true,
      instances: [{ browser: 'chromium' }],
    },
    globals: true,
    setupFiles: ['./src/test/browser-setup.ts'],
    include: ['src/**/*.browser.test.tsx'],
  },
});
