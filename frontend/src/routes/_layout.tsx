import { AppShell, Burger, Group, NavLink, Stack, Text, useMantineTheme } from '@mantine/core';
import { Outlet, NavLink as RouterLink, useLocation } from 'react-router';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { useContext, useMemo } from 'react';
import type { ComponentType } from 'react';
import {
  IconHome,
  IconCategory,
  IconLayoutColumns,
  IconAdjustments,
  IconPlaylist,
  IconBook,
  IconUser,
  IconShield,
} from '../components/icons';
import { AuthContext } from '../auth/AuthProvider';
import { UserMenu } from '../components/UserMenu';
import { PlaybackProvider } from '../features/playback/PlaybackProvider';
import { DevicePickerSurface } from '../features/playback/DevicePickerSurface';

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
  { path: '/playlists', labelKey: 'appshell.playlists', Icon: IconPlaylist },
  { path: '/library', labelKey: 'appshell.library', Icon: IconBook },
  { path: '/profile', labelKey: 'appshell.profile', Icon: IconUser },
];

export function AppShellLayout() {
  return (
    <PlaybackProvider>
      <AppShellInner />
      <PlaybackChrome />
    </PlaybackProvider>
  );
}

export function AppShellInner() {
  const { t } = useTranslation();
  const theme = useMantineTheme();
  const isDesktop = useMediaQuery(`(min-width: ${theme.breakpoints.md})`);
  const [navCollapsed, { toggle: toggleNav }] = useDisclosure(false);
  const location = useLocation();
  const auth = useContext(AuthContext);
  const isAdmin =
    auth?.state.status === 'authenticated' && auth.state.user.is_admin === true;
  const navItems = useMemo<NavItem[]>(
    () =>
      isAdmin
        ? [...NAV_ITEMS, { path: '/admin', labelKey: 'appshell.admin', Icon: IconShield }]
        : NAV_ITEMS,
    [isAdmin],
  );

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={
        isDesktop
          ? { width: 240, breakpoint: 'md', collapsed: { desktop: navCollapsed, mobile: true } }
          : undefined
      }
      footer={isDesktop ? undefined : { height: 64 }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            {isDesktop && (
              <Burger
                opened={!navCollapsed}
                onClick={toggleNav}
                size="sm"
                aria-label={t('appshell.toggle_nav')}
                aria-expanded={!navCollapsed}
              />
            )}
            <Text fw={700} size="lg">
              {t('appshell.wordmark')}
            </Text>
          </Group>
          <UserMenu />
        </Group>
      </AppShell.Header>

      {isDesktop && (
        <AppShell.Navbar p="sm">
          <Stack gap="xs">
            {navItems.map(({ path, labelKey, Icon }) => (
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
            {navItems.map(({ path, labelKey, Icon }) => {
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

export function PlaybackChrome() {
  return (
    <>
      <DevicePickerSurface />
    </>
  );
}
