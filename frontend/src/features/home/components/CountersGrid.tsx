import { Card, SimpleGrid, Stack, Text, UnstyledButton } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Ghost, GhostScope } from '../../../components/Ghost';

export interface CountersGridProps {
  /** undefined while loading: ghost numbers. */
  awaitingTriage: number | undefined;
  activeBlocks: number | undefined;
}

function Counter({ value, label }: { value: number | undefined; label: string }) {
  return (
    <UnstyledButton component={Link} to="/triage">
      <Card withBorder padding="md" radius="md">
        <Stack gap={4}>
          <Ghost>
            <Text ff="monospace" fz={32} fw={600} lh={1}>
              {value ?? '00'}
            </Text>
          </Ghost>
          <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
            {label}
          </Text>
        </Stack>
      </Card>
    </UnstyledButton>
  );
}

export function CountersGrid({ awaitingTriage, activeBlocks }: CountersGridProps) {
  const { t } = useTranslation();
  return (
    <GhostScope on={awaitingTriage === undefined}>
      <SimpleGrid cols={2} spacing="xs">
        <Counter value={awaitingTriage} label={t('home.counters.awaiting_triage')} />
        <Counter value={activeBlocks} label={t('home.counters.active_blocks')} />
      </SimpleGrid>
    </GhostScope>
  );
}
