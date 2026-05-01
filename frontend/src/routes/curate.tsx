import { useTranslation } from 'react-i18next';
import { EmptyState } from '../components/EmptyState';
import { IconAdjustments } from '../components/icons';

export function CuratePage() {
  const { t } = useTranslation();
  return (
    <EmptyState
      icon={<IconAdjustments size={32} />}
      title={`${t('appshell.curate')} — ${t('empty_state.coming_soon_title').toLowerCase()}`}
      body={t('empty_state.coming_soon_body')}
    />
  );
}
