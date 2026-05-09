import { Anchor, Card, Group, Stack, Text, UnstyledButton } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TriageBlockSummary } from '../../triage/hooks/useTriageBlocksByStyle';
import { weekLabel } from '../lib/weekLabel';

export interface ActiveBlocksListProps {
  blocks: TriageBlockSummary[];
  total: number;
}

export function ActiveBlocksList({ blocks, total }: ActiveBlocksListProps) {
  const { t } = useTranslation();
  return (
    <Card withBorder padding="md" radius="md">
      <Stack gap="xs">
        <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
          {t('home.active_blocks.title')}
        </Text>
        {blocks.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t('home.active_blocks.empty_body')}
          </Text>
        ) : (
          <Stack gap={4}>
            {blocks.map((b) => (
              <UnstyledButton key={b.id} component={Link} to={`/triage/${b.style_id}/${b.id}`}>
                <Group justify="space-between" wrap="nowrap" px="xs" py={6}>
                  <Text size="sm">
                    {weekLabel(b.date_from)} · {b.style_name}
                  </Text>
                  <Text size="sm" ff="monospace">
                    {b.track_count}
                  </Text>
                </Group>
              </UnstyledButton>
            ))}
            {total > blocks.length && (
              <Anchor component={Link} to="/triage" size="sm" mt={6}>
                {t('home.active_blocks.view_all', { count: total })}
              </Anchor>
            )}
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
