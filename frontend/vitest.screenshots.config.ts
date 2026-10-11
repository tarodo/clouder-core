import { defineConfig } from 'vitest/config';
import { playwright } from '@vitest/browser-playwright';
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
  // vitest 4 checks screenshot paths against server.fs: allow the project and the
  // README image folder, nothing else.
  server: { fs: { allow: [__dirname, path.resolve(__dirname, '../docs/assets')] } },
  // Pre-bundle what only the screenshots import: a dependency found mid-run reloads the
  // page and the running shot sees a second React ("reading 'useCallback'").
  optimizeDeps: { include: ['zustand'] },
  test: {
    browser: {
      enabled: true,
      // Same picture on any machine: fixed locale and timezone.
      // Headless vitest 4 sizes the page from contextOptions only (Playwright's 1280x720
      // otherwise), which shrank the 1800px frame to ~0.7x.
      provider: playwright({
        contextOptions: { locale: 'en-US', timezoneId: 'UTC', viewport: { width: 1800, height: 1000 } },
      }),
      headless: true,
      instances: [{ browser: 'chromium' }],
    },
    globals: true,
    setupFiles: ['./src/test/browser-setup.ts'],
    include: ['src/screenshots/**/*.shot.tsx'],
  },
});
