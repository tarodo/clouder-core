import { Card, SimpleGrid, Stack, Text, UnstyledButton } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';

export interface CountersGridProps {
  awaitingTriage: number;
  activeBlocks: number;
}

export function CountersGrid({ awaitingTriage, activeBlocks }: CountersGridProps) {
  const { t } = useTranslation();
  return (
    <SimpleGrid cols={2} spacing="xs">
      <UnstyledButton component={Link} to="/triage">
        <Card withBorder padding="md" radius="md">
          <Stack gap={4}>
            <Text ff="monospace" fz={32} fw={600} lh={1}>
              {awaitingTriage}
            </Text>
            <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
              {t('home.counters.awaiting_triage')}
            </Text>
          </Stack>
        </Card>
      </UnstyledButton>
      <UnstyledButton component={Link} to="/triage">
        <Card withBorder padding="md" radius="md">
          <Stack gap={4}>
            <Text ff="monospace" fz={32} fw={600} lh={1}>
              {activeBlocks}
            </Text>
            <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
              {t('home.counters.active_blocks')}
            </Text>
          </Stack>
        </Card>
      </UnstyledButton>
    </SimpleGrid>
  );
}
