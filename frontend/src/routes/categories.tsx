import { useTranslation } from 'react-i18next';
import { EmptyState } from '../components/EmptyState';
import { IconCategory } from '../components/icons';

export function CategoriesPage() {
  const { t } = useTranslation();
  return (
    <EmptyState
      icon={<IconCategory size={32} />}
      title={`${t('appshell.categories')} — ${t('empty_state.coming_soon_title').toLowerCase()}`}
      body={t('empty_state.coming_soon_body')}
    />
  );
}
