/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// `/auth/return` is a SPA route owned by AuthReturnPage. Everything else
// under /auth/* is a backend endpoint and must be proxied to API GW.
const PROXIED_PREFIXES = [
  '/auth/login',
  '/auth/callback',
  '/auth/refresh',
  '/auth/logout',
  '/me',
  '/categories',
  '/styles',
  '/tracks',
  '/artists',
  '/labels',
  '/albums',
  '/triage',
  '/runs',
  '/collect_bp_releases',
];

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const target = env.VITE_API_BASE_URL ?? '';

  const proxy = Object.fromEntries(
    PROXIED_PREFIXES.map((prefix) => [
      prefix,
      {
        target,
        changeOrigin: true,
        secure: true,
        cookieDomainRewrite: '',
      },
    ]),
  );

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
