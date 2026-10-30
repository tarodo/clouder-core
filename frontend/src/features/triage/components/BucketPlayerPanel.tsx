import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { usePlaybackHotkeys } from '../../playback/usePlaybackHotkeys';
import {
  TrackCards,
  TrackPlayer,
  transportHotkeys,
  usePlayingRow,
} from '../../playback/TrackPlayer';
import type { BucketTrack } from '../hooks/useBucketTracks';
import { useTriageBlock } from '../hooks/useTriageBlock';
import { useBucketDistribute } from '../hooks/useBucketDistribute';
import { BucketDistributeButtons } from './BucketDistributeButtons';
import { moveDestinationsFor } from '../lib/bucketLabels';
import { suggestedDestinations, suggestionTag } from '../lib/suggestedDestinations';
import { bucketTrackInfo } from '../lib/toPlaybackTrack';
import { AnalysisMeta } from './AnalysisMeta';
import classes from './BucketPlayerPanel.module.css';

export interface BucketPlayerPanelProps {
  blockId: string;
  bucketId: string;
  /** Visible bucket tracks, used to look up label/BPM for the playing track. */
  items: BucketTrack[];
}

export function BucketPlayerPanel({ blockId, bucketId, items }: BucketPlayerPanelProps) {
  const { t } = useTranslation();
  const playback = usePlayback();

  const { data: block } = useTriageBlock(blockId);
  const blockBuckets = block?.buckets ?? [];
  const distribute = useBucketDistribute({
    blockId,
    bucketId,
    styleId: block?.style_id ?? '',
    buckets: blockBuckets,
  });
  const destinations =
    block?.status === 'IN_PROGRESS'
      ? moveDestinationsFor(blockBuckets, bucketId).filter(
          (b) => b.bucket_type === 'STAGING' || b.bucket_type === 'DISCARD',
        )
      : [];

  const row = usePlayingRow(items, (it) => it.track_id);
  const info = row && bucketTrackInfo(row);
  const suggested = suggestedDestinations(row?.prediction, blockBuckets);

  usePlaybackHotkeys(transportHotkeys(playback));

  return (
    <TrackPlayer
      className={classes.root}
      info={info}
      empty={t('triage.bucket_player.empty.pick_track')}
      meta={
        row && (
          <AnalysisMeta
            aiVerdict={row.ai_verdict}
            aiChecked={row.ai_checked}
            profiled={row.profiled}
          />
        )
      }
    >
      {() => (
        <>
          <BucketDistributeButtons
            destinations={destinations}
            suggested={suggested}
            onDistribute={(id) => distribute(id, suggestionTag(suggested, id))}
          />
          <TrackCards info={info} />
        </>
      )}
    </TrackPlayer>
  );
}
