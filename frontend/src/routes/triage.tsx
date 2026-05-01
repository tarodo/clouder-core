import { useTranslation } from 'react-i18next';
import { EmptyState } from '../components/EmptyState';
import { IconLayoutColumns } from '../components/icons';

export function TriagePage() {
  const { t } = useTranslation();
  return (
    <EmptyState
      icon={<IconLayoutColumns size={32} />}
      title={`${t('appshell.triage')} — ${t('empty_state.coming_soon_title').toLowerCase()}`}
      body={t('empty_state.coming_soon_body')}
    />
  );
}
