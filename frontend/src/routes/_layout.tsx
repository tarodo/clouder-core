import { AppShell, Group, NavLink, Stack, Text, useMantineTheme } from '@mantine/core';
import { Outlet, NavLink as RouterLink, useLocation } from 'react-router';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import type { ComponentType } from 'react';
import {
  IconHome,
  IconCategory,
  IconLayoutColumns,
  IconAdjustments,
  IconUser,
} from '../components/icons';
import { UserMenu } from '../components/UserMenu';

interface NavItem {
  path: string;
  labelKey: string;
  Icon: ComponentType<{ size?: number }>;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/', labelKey: 'appshell.home', Icon: IconHome },
  { path: '/categories', labelKey: 'appshell.categories', Icon: IconCategory },
  { path: '/triage', labelKey: 'appshell.triage', Icon: IconLayoutColumns },
  { path: '/curate', labelKey: 'appshell.curate', Icon: IconAdjustments },
  { path: '/profile', labelKey: 'appshell.profile', Icon: IconUser },
];

export function AppShellLayout() {
  const { t } = useTranslation();
  const theme = useMantineTheme();
  const isDesktop = useMediaQuery(`(min-width: ${theme.breakpoints.md})`);
  const location = useLocation();

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={isDesktop ? { width: 240, breakpoint: 'md' } : undefined}
      footer={isDesktop ? undefined : { height: 64 }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Text fw={700} size="lg">
            {t('appshell.wordmark')}
          </Text>
          <UserMenu />
        </Group>
      </AppShell.Header>

      {isDesktop && (
        <AppShell.Navbar p="sm">
          <Stack gap="xs">
            {NAV_ITEMS.map(({ path, labelKey, Icon }) => (
              <NavLink
                key={path}
                component={RouterLink}
                to={path}
                end={path === '/'}
                label={t(labelKey)}
                leftSection={<Icon size={18} />}
                active={
                  path === '/' ? location.pathname === '/' : location.pathname.startsWith(path)
                }
              />
            ))}
          </Stack>
        </AppShell.Navbar>
      )}

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>

      {!isDesktop && (
        <AppShell.Footer p={0}>
          <Group h="100%" justify="space-around" align="center" gap={0}>
            {NAV_ITEMS.map(({ path, labelKey, Icon }) => {
              const active =
                path === '/' ? location.pathname === '/' : location.pathname.startsWith(path);
              return (
                <RouterLink
                  key={path}
                  to={path}
                  end={path === '/'}
                  style={{
                    flex: 1,
                    textAlign: 'center',
                    padding: '8px 0',
                    color: active ? 'var(--color-fg)' : 'var(--color-fg-muted)',
                    textDecoration: 'none',
                  }}
                  aria-label={t(labelKey)}
                >
                  <Stack gap={2} align="center">
                    <Icon size={20} />
                    <Text size="xs">{t(labelKey)}</Text>
                  </Stack>
                </RouterLink>
              );
            })}
          </Group>
        </AppShell.Footer>
      )}
    </AppShell>
  );
}
