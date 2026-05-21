import { Button, SimpleGrid, Stack, Text } from '@mantine/core';
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
      <SimpleGrid cols={{ base: 2, md: 3 }} spacing="xs" verticalSpacing="xs">
        {destinations.map((b) => {
          const label = bucketLabel(b, t);
          return (
            <Button
              key={b.id}
              variant={b.bucket_type === 'DISCARD' ? 'light' : 'default'}
              color={b.bucket_type === 'DISCARD' ? 'red' : undefined}
              size="sm"
              onClick={() => onDistribute(b.id)}
              aria-label={label}
              styles={{ label: { whiteSpace: 'normal' } }}
            >
              {label}
            </Button>
          );
        })}
      </SimpleGrid>
    </Stack>
  );
}
