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
  const visible = buckets.filter((b) => b.id !== currentBucketId);

  const stagingSlots = resolveStagingHotkeys(visible);
  const overflow = stagingOverflow(visible);

  const newBucket = byTechType(visible, 'NEW');
  const oldBucket = byTechType(visible, 'OLD');
  const notBucket = byTechType(visible, 'NOT');
  const discardBucket = byDiscard(visible);

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
    return (
      <DestinationButton
        key={bucket.id}
        bucket={bucket}
        hotkeyHint={isMobile ? null : hotkeyHint}
        justTapped={lastTappedBucketId === bucket.id}
        disabled={false}
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
