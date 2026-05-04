import { useEffect } from 'react';
import { Navigate, useParams } from 'react-router';
import { CurateSession } from '../components/CurateSession';
import {
  writeLastCurateLocation,
  writeLastCurateStyle,
} from '../lib/lastCurateLocation';

export function CurateSessionPage() {
  const params = useParams<{ styleId: string; blockId: string; bucketId: string }>();
  const { styleId, blockId, bucketId } = params;

  useEffect(() => {
    if (!styleId || !blockId || !bucketId) return;
    document.body.classList.add('accent-magenta');
    writeLastCurateLocation(styleId, blockId, bucketId);
    writeLastCurateStyle(styleId);
    return () => {
      document.body.classList.remove('accent-magenta');
    };
  }, [styleId, blockId, bucketId]);

  if (!styleId || !blockId || !bucketId) {
    return <Navigate to="/curate" replace />;
  }
  return <CurateSession styleId={styleId} blockId={blockId} bucketId={bucketId} />;
}
