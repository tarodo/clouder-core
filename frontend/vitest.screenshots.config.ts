/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

/**
 * README screenshots — real components, sample data (pnpm screenshots).
 *
 * Run with: pnpm screenshots
 * Same harness as vitest.browser.config.ts.
 * Writes docs/assets/*.png; not part of pnpm test or pnpm test:browser.
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
      // Same picture on any machine: fixed locale and timezone.
      providerOptions: { context: { locale: 'en-US', timezoneId: 'UTC' } },
    },
    globals: true,
    setupFiles: ['./src/test/browser-setup.ts'],
    include: ['src/screenshots/**/*.shot.tsx'],
  },
});
