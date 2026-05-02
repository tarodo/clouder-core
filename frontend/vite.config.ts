/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// `/auth/return` is a SPA route owned by AuthReturnPage. Everything else
// under /auth/* is a backend endpoint and must be proxied to API GW.
//
// `BACKEND_ONLY_PREFIXES` are always proxied — they have no SPA equivalent.
// `SPA_AWARE_PREFIXES` collide with client-side SPA routes (`/categories/*`,
// `/triage/*`); for those we proxy `Accept: application/json` calls from the
// SPA but bypass to `/index.html` for browser navigations (F5, deep-link
// paste — they send `Accept: text/html`) so the router can render the page.
const BACKEND_ONLY_PREFIXES = [
  '/auth/login',
  '/auth/callback',
  '/auth/refresh',
  '/auth/logout',
  '/me',
  '/styles',
  '/tracks',
  '/artists',
  '/labels',
  '/albums',
  '/runs',
  '/collect_bp_releases',
];
const SPA_AWARE_PREFIXES = ['/categories', '/triage'];

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const target = env.VITE_API_BASE_URL ?? '';

  const baseOpts = { target, changeOrigin: true, secure: true, cookieDomainRewrite: '' };
  const spaAwareOpts = {
    ...baseOpts,
    bypass: (req: { method?: string; headers: Record<string, string | string[] | undefined> }) => {
      if (req.method !== 'GET') return undefined;
      const accept = req.headers.accept;
      const acceptStr = Array.isArray(accept) ? accept.join(',') : accept;
      if (typeof acceptStr === 'string' && acceptStr.includes('text/html')) {
        return '/index.html';
      }
      return undefined;
    },
  };

  const proxy = {
    ...Object.fromEntries(BACKEND_ONLY_PREFIXES.map((p) => [p, baseOpts])),
    ...Object.fromEntries(SPA_AWARE_PREFIXES.map((p) => [p, spaAwareOpts])),
  };

  return {
    plugins: [react()],
    resolve: {
      alias: { '@': path.resolve(__dirname, 'src') },
    },
    server: { host: '127.0.0.1', port: 5173, proxy: target ? proxy : undefined },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      include: ['src/**/*.{test,spec}.{ts,tsx}'],
      // jsdom URL must be 'http://localhost/' — MSW handlers and apiClient
      // both expect that origin (added in Phase C, kept verbatim).
      environmentOptions: {
        jsdom: { url: 'http://localhost/' },
      },
      coverage: {
        provider: 'v8',
        include: ['src/**/*.{ts,tsx}'],
        exclude: [
          'src/**/*.{test,spec}.{ts,tsx}',
          'src/test/**',
          'src/main.tsx',
          'src/api/schema.d.ts',
        ],
      },
    },
  };
});
