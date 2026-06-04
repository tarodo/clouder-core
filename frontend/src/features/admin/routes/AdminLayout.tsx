import { Container, Stack, Tabs } from '@mantine/core';
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
  ];

  const active =
    TAB_VALUES.find((v) => location.pathname.startsWith(v)) ?? '/admin/coverage';

  return (
    <Container size="xl" py="md">
      <Stack gap="md">
        <Tabs value={active} onChange={(v) => v && navigate(v)} keepMounted={false}>
          <Tabs.List>
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
