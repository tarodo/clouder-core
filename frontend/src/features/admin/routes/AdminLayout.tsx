import { Stack, Tabs } from '@mantine/core';
import { Outlet, useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { RunProgressToast } from '../components/RunProgressToast';

// Order longest-first so /admin/labels/enrich/runs matches before /admin/labels/enrich
// when computing the active tab via startsWith.
const TAB_VALUES = [
  '/admin/labels/enrich/runs',
  '/admin/labels/enrich',
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
    { value: '/admin/auto-enrich', label: t('admin_auto_enrich.title') },
  ];

  const active =
    TAB_VALUES.find((v) => location.pathname.startsWith(v)) ?? '/admin/coverage';

  return (
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
  );
}
