import { Navigate } from 'react-router';
import { useStyles } from '../../../hooks/useStyles';
import { CurateSkeleton } from '../components/CurateSkeleton';
import { readLastCurateStyle } from '../lib/lastCurateLocation';

export function CurateIndexRedirect() {
  const styles = useStyles();
  if (styles.isLoading) return <CurateSkeleton />;
  const items = styles.data?.items ?? [];
  if (styles.isError || !styles.data || items.length === 0) {
    return <Navigate to="/categories" replace />;
  }
  const last = readLastCurateStyle();
  const target = last && items.some((s) => s.id === last) ? last : items[0]?.id;
  if (!target) return <Navigate to="/categories" replace />;
  return <Navigate to={`/curate/${target}`} replace />;
}
