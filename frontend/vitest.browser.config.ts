/// <reference types="vitest" />
import { defineConfig } from 'vite';
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
    // @ts-expect-error — browser config is typed at the vitest level, not vite
    browser: {
      enabled: true,
      provider: 'playwright',
      headless: true,
      name: 'chromium',
    },
    globals: true,
    setupFiles: ['./src/test/browser-setup.ts'],
    include: ['src/**/*.browser.test.tsx'],
  },
});
