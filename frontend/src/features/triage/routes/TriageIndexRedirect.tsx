import { Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useStyles } from '../../../hooks/useStyles';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { EmptyState } from '../../../components/EmptyState';
import { IconLayoutColumns } from '../../../components/icons';
import { readLastVisitedTriageStyle } from '../lib/lastVisitedTriageStyle';

export function TriageIndexRedirect() {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useStyles();

  if (isLoading) return <FullScreenLoader />;
  if (isError || !data) {
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }

  const items = data.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        icon={<IconLayoutColumns size={32} />}
        title={t('categories.no_styles.title')}
        body={t('categories.no_styles.body')}
      />
    );
  }

  const last = readLastVisitedTriageStyle();
  const target = items.find((s) => s.id === last)?.id ?? items[0]?.id;
  if (!target) return null;
  return <Navigate to={`/triage/${target}`} replace />;
}
