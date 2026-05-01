import { useTranslation } from 'react-i18next';
import { EmptyState } from '../components/EmptyState';
import { IconHome } from '../components/icons';

export function HomePage() {
  const { t } = useTranslation();
  return (
    <EmptyState
      icon={<IconHome size={32} />}
      title={`${t('appshell.home')} — ${t('empty_state.coming_soon_title').toLowerCase()}`}
      body={t('empty_state.coming_soon_body')}
    />
  );
}
