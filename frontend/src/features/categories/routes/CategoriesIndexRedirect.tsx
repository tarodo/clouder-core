import { Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useStyles } from '../hooks/useStyles';
import { readLastVisitedStyle } from '../lib/lastVisitedStyle';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { EmptyState } from '../../../components/EmptyState';

export function CategoriesIndexRedirect() {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useStyles();
  if (isLoading) return <FullScreenLoader />;
  if (isError || !data) {
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }
  const items = data.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState title={t('categories.no_styles.title')} body={t('categories.no_styles.body')} />
    );
  }
  const last = readLastVisitedStyle();
  const target = items.find((s) => s.id === last)?.id ?? items[0]?.id;
  if (!target) return null;
  return <Navigate to={`/categories/${target}`} replace />;
}
