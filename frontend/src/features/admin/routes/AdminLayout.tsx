import { Tabs } from '@mantine/core';
import { Outlet, useLocation, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { RunProgressToast } from '../components/RunProgressToast';

const TAB_VALUES = ['/admin/coverage', '/admin/spotify-not-found'] as const;

export function AdminLayout() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();

  const TABS = [
    { value: '/admin/coverage', label: t('admin.tabs.coverage') },
    { value: '/admin/spotify-not-found', label: t('admin.tabs.spotify_not_found') },
  ];

  const active =
    TAB_VALUES.find((v) => location.pathname.startsWith(v)) ?? TAB_VALUES[0];
  return (
    <>
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
    </>
  );
}
