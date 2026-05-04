import { useMemo } from 'react';
import { Navigate, useParams } from 'react-router';
import { useTriageBlock } from '../../triage/hooks/useTriageBlock';
import { CurateSetupPage } from '../components/CurateSetupPage';
import { CurateSkeleton } from '../components/CurateSkeleton';
import {
  clearLastCurateLocation,
  isStaleLocation,
  readLastCurateLocation,
} from '../lib/lastCurateLocation';

export function CurateStyleResume() {
  const { styleId } = useParams<{ styleId: string }>();
  const stored = useMemo(
    () => (styleId ? readLastCurateLocation(styleId) : null),
    [styleId],
  );
  const blockQuery = useTriageBlock(stored?.blockId ?? '');

  if (!styleId) return <Navigate to="/curate" replace />;
  if (!stored) return <CurateSetupPage styleId={styleId} />;
  if (blockQuery.isLoading) return <CurateSkeleton />;
  if (blockQuery.isError || !blockQuery.data) {
    clearLastCurateLocation(styleId);
    return <CurateSetupPage styleId={styleId} />;
  }
  if (isStaleLocation(stored, blockQuery.data)) {
    clearLastCurateLocation(styleId);
    return <CurateSetupPage styleId={styleId} />;
  }
  return <Navigate to={`/curate/${styleId}/${stored.blockId}/${stored.bucketId}`} replace />;
}
