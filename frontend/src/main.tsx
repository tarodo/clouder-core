import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router';

import './tokens.css';
import '@mantine/core/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/notifications/styles.css';

import './i18n';
import { clouderTheme } from './theme';
import { queryClient } from './lib/queryClient';
import { AuthProvider } from './auth/AuthProvider';
import { router } from './routes/router';

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('#root missing');

createRoot(rootEl).render(
  <StrictMode>
    <MantineProvider theme={clouderTheme} defaultColorScheme="light">
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
