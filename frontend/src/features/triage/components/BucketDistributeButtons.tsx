import { Chip, Group, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export interface BucketDistributeButtonsProps {
  destinations: TriageBucket[];
  onDistribute: (toBucketId: string) => void;
}

export function BucketDistributeButtons({
  destinations,
  onDistribute,
}: BucketDistributeButtonsProps) {
  const { t } = useTranslation();
  if (destinations.length === 0) return null;
  return (
    <Stack gap="xs" data-testid="bucket-distribute">
      <Text
        ff="monospace"
        fz={10}
        c="var(--color-fg-muted)"
        tt="uppercase"
        style={{ letterSpacing: '0.1em' }}
      >
        {t('triage.bucket_player.distribute.heading')}
      </Text>
      <Group gap="xs" wrap="wrap">
        {destinations.map((b) => (
          <Chip
            key={b.id}
            checked={false}
            size="sm"
            variant="outline"
            color={b.bucket_type === 'DISCARD' ? 'red' : undefined}
            onChange={() => onDistribute(b.id)}
          >
            {bucketLabel(b, t)}
          </Chip>
        ))}
      </Group>
    </Stack>
  );
}
