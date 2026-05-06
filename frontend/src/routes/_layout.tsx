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
import { PlaybackProvider } from '../features/playback/PlaybackProvider';
import { MiniBar } from '../features/playback/MiniBar';
import { DevicePickerSurface } from '../features/playback/DevicePickerSurface';
import { DeviceIndicator } from '../features/playback/DeviceIndicator';
import { LeaveContextDialog } from '../features/playback/LeaveContextDialog';
import { usePlayback } from '../features/playback/usePlayback';
import { hasPlayerCard } from '../features/playback/routeContext';
import { readLastCurateStyle } from '../features/curate/lib/lastCurateLocation';

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
  return (
    <PlaybackProvider>
      <AppShellInner />
      <PlaybackChrome />
    </PlaybackProvider>
  );
}

function AppShellInner() {
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

export function PlaybackChrome() {
  const playback = usePlayback();
  const { devices } = playback;
  const location = useLocation();

  const status = playback.queue.status;
  const onPlayerCardRoute = hasPlayerCard(location.pathname);
  const showMini =
    !onPlayerCardRoute &&
    playback.queue.source !== null &&
    playback.track.current !== null &&
    (status === 'playing' || status === 'paused' || status === 'buffering');

  // Reconstruct source href for MiniBar's title link. The PlaybackProvider's
  // queue.source carries blockId + bucketId but not styleId. Read the most
  // recent styleId from F5's localStorage helper. If unknown, fall back to a
  // sentinel slug so the link still navigates somewhere predictable; the F5
  // resume route is responsible for resolving the right style itself.
  const source = playback.queue.source;
  const styleId = readLastCurateStyle() ?? '_resume';
  const sourceHref = source
    ? `/curate/${styleId}/${source.blockId}/${source.bucketId}`
    : '/';

  const queueActive = status !== 'idle' && status !== 'ended';

  return (
    <>
      {showMini && playback.track.current ? (
        <MiniBar
          track={playback.track.current}
          state={status}
          sourceHref={sourceHref}
          onPlayPause={() => void playback.controls.togglePlayPause()}
          onClose={() => playback.controls.clearQueue()}
          deviceIndicator={
            <DeviceIndicator
              mode="compact"
              active={devices.active}
              cloderTabId={devices.cloderTabId}
              onOpen={(anchor) => devices.open(anchor)}
            />
          }
        />
      ) : null}
      <LeaveContextDialog
        active={queueActive}
        currentPath={location.pathname}
        onConfirm={() => playback.controls.clearQueue()}
      />
      <DevicePickerSurface />
    </>
  );
}
