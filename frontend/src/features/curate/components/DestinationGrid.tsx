// frontend/src/features/curate/components/DestinationGrid.tsx
import { Menu, SimpleGrid, Stack, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { DestinationButton } from './DestinationButton';
import {
  bucketLabel,
  type TriageBucket,
} from '../../triage/lib/bucketLabels';
import {
  byDiscard,
  byTechType,
  resolveStagingHotkeys,
  stagingOverflow,
} from '../lib/destinationMap';

export interface DestinationGridProps {
  buckets: TriageBucket[];
  currentBucketId: string;
  lastTappedBucketId: string | null;
  onAssign: (toBucketId: string) => void;
}

/**
 * Layout follows P-22 mobile + P-23 desktop:
 *  - DISCARD button stands alone at the top (full-width).
 *  - Staging categories form a tile grid (2-col on mobile, 3-col on desktop).
 *  - Technical buckets (NEW/OLD/NOT) sit at the bottom in a 3-col grid.
 *  - Section labels are mono uppercase muted text.
 */
export function DestinationGrid({
  buckets,
  currentBucketId,
  lastTappedBucketId,
  onAssign,
}: DestinationGridProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  // Staging slots exclude the current bucket entirely (and inactive ones,
  // by resolveStagingHotkeys). Technical buckets stay in the layout even
  // when the user is currently curating from one of them — render the
  // self-bucket as disabled so it's clear the bucket exists but can't be
  // a destination of itself.
  const stagingSource = buckets.filter((b) => b.id !== currentBucketId);
  const stagingSlots = resolveStagingHotkeys(stagingSource);
  const overflow = stagingOverflow(stagingSource);

  const newBucket = byTechType(buckets, 'NEW');
  const oldBucket = byTechType(buckets, 'OLD');
  const notBucket = byTechType(buckets, 'NOT');
  const discardBucket = byDiscard(buckets);

  const sectionLabel = (text: string) => (
    <Text
      ff="monospace"
      fz={10}
      c="var(--color-fg-muted)"
      tt="uppercase"
      style={{ letterSpacing: '0.1em' }}
    >
      {text}
    </Text>
  );

  const renderBtn = (
    bucket: TriageBucket | null,
    hotkeyHint: string | null,
  ) => {
    if (!bucket) return null;
    const isSelf = bucket.id === currentBucketId;
    return (
      <DestinationButton
        key={bucket.id}
        bucket={bucket}
        hotkeyHint={isMobile ? null : hotkeyHint}
        justTapped={lastTappedBucketId === bucket.id}
        disabled={isSelf}
        onClick={() => onAssign(bucket.id)}
      />
    );
  };

  return (
    <Stack gap="md" data-testid="destination-grid">
      {discardBucket && renderBtn(discardBucket, '0')}

      {(stagingSlots.length > 0 || overflow.length > 0) && (
        <Stack gap="xs">
          {sectionLabel(t('curate.destination.group_staging'))}
          <SimpleGrid cols={{ base: 2, md: 3 }} spacing="xs" verticalSpacing="xs">
            {stagingSlots.map((b, idx) => renderBtn(b, String(idx + 1)))}
            {overflow.length > 0 && (
              <Menu position="bottom-end" withinPortal>
                <Menu.Target>
                  <DestinationButton
                    bucket={{
                      id: '__overflow__',
                      bucket_type: 'STAGING',
                      inactive: false,
                      track_count: 0,
                      category_id: null,
                      category_name: t('curate.destination.more_categories'),
                    }}
                    hotkeyHint={null}
                    justTapped={false}
                    disabled={false}
                    onClick={() => {}}
                  />
                </Menu.Target>
                <Menu.Dropdown>
                  {overflow.map((b) => (
                    <Menu.Item key={b.id} onClick={() => onAssign(b.id)}>
                      {bucketLabel(b, t)}
                    </Menu.Item>
                  ))}
                </Menu.Dropdown>
              </Menu>
            )}
          </SimpleGrid>
        </Stack>
      )}

      {(newBucket || oldBucket || notBucket) && (
        <Stack gap="xs">
          {sectionLabel(t('curate.destination.group_technical'))}
          <SimpleGrid cols={3} spacing="xs" verticalSpacing="xs">
            {renderBtn(newBucket, 'Q')}
            {renderBtn(oldBucket, 'W')}
            {renderBtn(notBucket, 'E')}
          </SimpleGrid>
        </Stack>
      )}
    </Stack>
  );
}
