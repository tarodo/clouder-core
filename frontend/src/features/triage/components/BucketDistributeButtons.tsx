import { Button, SimpleGrid, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';
import { suggestionLevel, type Suggested } from '../lib/suggestedDestinations';

export interface BucketDistributeButtonsProps {
  destinations: TriageBucket[];
  onDistribute: (toBucketId: string) => void;
  /** Lit buttons for the playing track. */
  suggested?: Suggested;
}

export function BucketDistributeButtons({
  destinations,
  onDistribute,
  suggested,
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
          const discard = b.bucket_type === 'DISCARD';
          const level = suggestionLevel(suggested, b.id);
          // Secondary is light in the theme's primary colour, never DISCARD's light red. The
          // monochrome theme's light fill is near-white, so the accent border carries it.
          const variant =
            level === 'primary' ? 'filled' : level === 'secondary' || discard ? 'light' : 'default';
          return (
            <Button
              key={b.id}
              variant={variant}
              color={discard ? 'red' : undefined}
              bd={level === 'secondary' ? '1px solid var(--color-accent)' : undefined}
              size="sm"
              onClick={() => onDistribute(b.id)}
              aria-label={level ? `${label}, ${t(`triage.suggested.${level}_aria`)}` : label}
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
