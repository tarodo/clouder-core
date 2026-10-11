import { StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router';

import './tokens.css';
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/charts/styles.css';

import './i18n';
import { clouderTheme } from './theme';
import { queryClient } from './lib/queryClient';
import { AuthProvider } from './auth/AuthProvider';
import { router } from './routes/router';

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('#root missing');
const root = rootEl;

async function boot(): Promise<void> {
  let banner: ReactNode = null;
  if (import.meta.env.MODE === 'demo') {
    // The demo's API runs in the browser (MSW) and must be up before AuthProvider
    // asks /auth/refresh. Production builds drop this branch and the demo chunk.
    const demo = await import('./demo/start');
    await demo.startDemo();
    banner = <demo.DemoBanner />;
  }
  createRoot(root).render(
    <StrictMode>
      <MantineProvider theme={clouderTheme} defaultColorScheme="light">
        <ModalsProvider>
          <Notifications position="top-right" />
          <QueryClientProvider client={queryClient}>
            <AuthProvider>
              <RouterProvider router={router} />
            </AuthProvider>
          </QueryClientProvider>
        </ModalsProvider>
        {banner}
      </MantineProvider>
    </StrictMode>,
  );
}

void boot();
