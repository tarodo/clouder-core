import { Container, Stack, Tabs } from '@mantine/core';
import { useEffect, useRef } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { RunProgressToast } from '../components/RunProgressToast';

// Order longest-first so /admin/labels/enrich/runs matches before /admin/labels/enrich
// and /admin/artists/enrich/runs matches before /admin/artists/enrich
// when computing the active tab via startsWith.
const TAB_VALUES = [
  '/admin/labels/enrich/runs',
  '/admin/labels/enrich',
  '/admin/artists/enrich/runs',
  '/admin/artists/enrich',
  '/admin/coverage',
  '/admin/spotify-not-found',
  '/admin/auto-enrich',
  '/admin/analytics',
] as const;

export function AdminLayout() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();

  const TABS = [
    { value: '/admin/coverage', label: t('admin.tabs.coverage') },
    { value: '/admin/spotify-not-found', label: t('admin.tabs.spotify_not_found') },
    { value: '/admin/labels/enrich', label: t('admin_enrichment.tabs.backlog') },
    { value: '/admin/labels/enrich/runs', label: t('admin_enrichment.tabs.runs') },
    { value: '/admin/artists/enrich', label: t('admin_enrichment.tabs.artist_backlog') },
    { value: '/admin/artists/enrich/runs', label: t('admin_enrichment.tabs.artist_runs') },
    { value: '/admin/auto-enrich', label: t('admin_auto_enrich.title') },
    { value: '/admin/analytics', label: t('admin.tabs.analytics') },
  ];

  const active =
    TAB_VALUES.find((v) => location.pathname.startsWith(v)) ?? '/admin/coverage';
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    listRef.current
      ?.querySelector('[data-active]')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [active]);

  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        {/* Eight tabs: one row that scrolls sideways on a phone, never wrapped rows. The root
            scrolls, so the list stays as wide as its tabs and its baseline runs under all of them. */}
        <Tabs
          value={active}
          onChange={(v) => v && navigate(v)}
          keepMounted={false}
          styles={{
            root: { overflowX: 'auto', scrollbarWidth: 'none' },
            list: { flexWrap: 'nowrap', width: 'max-content', minWidth: '100%' },
          }}
        >
          <Tabs.List ref={listRef}>
            {TABS.map((tab) => (
              <Tabs.Tab key={tab.value} value={tab.value}>
                {tab.label}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>
        <Outlet />
        <RunProgressToast />
      </Stack>
    </Container>
  );
}
