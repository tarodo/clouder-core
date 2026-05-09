import { Tabs } from '@mantine/core';
import { Outlet, useLocation, useNavigate } from 'react-router';
import { RunProgressToast } from '../components/RunProgressToast';

const TABS = [
  { value: '/admin/coverage', label: 'Coverage' },
  { value: '/admin/spotify-not-found', label: 'Tracks not on Spotify' },
];

export function AdminLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const active =
    TABS.find((t) => location.pathname.startsWith(t.value))?.value ?? TABS[0].value;
  return (
    <>
      <Tabs value={active} onChange={(v) => v && navigate(v)} keepMounted={false}>
        <Tabs.List>
          {TABS.map((t) => (
            <Tabs.Tab key={t.value} value={t.value}>
              {t.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      <Outlet />
      <RunProgressToast />
    </>
  );
}
