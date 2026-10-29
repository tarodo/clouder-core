import { Anchor, Card, Group, Stack, Text, UnstyledButton } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Ghost, GhostScope, useRemembered } from '../../../components/Ghost';
import type { TriageBlockSummary } from '../../triage/hooks/useTriageBlocksByStyle';
import { weekLabel } from '../lib/weekLabel';

export interface ActiveBlocksListProps {
  /** undefined while loading: as many ghost rows as last time. */
  blocks: TriageBlockSummary[] | undefined;
  total: number;
}

const ghostBlock = (i: number): TriageBlockSummary => ({
  id: `ghost-${i}`,
  style_id: '',
  style_name: 'Melodic House & Techno',
  name: '',
  date_from: '2026-10-03',
  date_to: '2026-10-09',
  status: 'IN_PROGRESS',
  created_at: '',
  updated_at: '',
  finalized_at: null,
  track_count: 30,
});

export function ActiveBlocksList(props: ActiveBlocksListProps) {
  const { t } = useTranslation();
  const ghost = props.blocks === undefined;
  const rows = useRemembered('home.active_blocks', props.blocks?.length, 2);
  const more = useRemembered(
    'home.active_blocks.more',
    ghost ? undefined : Number(props.total > props.blocks!.length),
    0,
  );
  const blocks = props.blocks ?? Array.from({ length: rows }, (_, i) => ghostBlock(i));
  const total = ghost ? rows + more : props.total;
  return (
    <GhostScope on={ghost}>
      <Card withBorder padding="md" radius="md">
        <Stack gap="xs">
          <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
            {t('home.active_blocks.title')}
          </Text>
          {blocks.length === 0 ? (
            <Ghost>
              <Text size="sm" c="dimmed">
                {t('home.active_blocks.empty_body')}
              </Text>
            </Ghost>
          ) : (
            <Stack gap={4}>
              {blocks.map((b) => (
                <UnstyledButton key={b.id} component={Link} to={`/triage/${b.style_id}/${b.id}`}>
                  <Group justify="space-between" wrap="nowrap" px="xs" py={6}>
                    <Ghost>
                      <Text size="sm">
                        {weekLabel(b.date_from)} · {b.style_name}
                      </Text>
                    </Ghost>
                    <Ghost>
                      <Text size="sm" ff="monospace">
                        {b.track_count}
                      </Text>
                    </Ghost>
                  </Group>
                </UnstyledButton>
              ))}
              {total > blocks.length && (
                <Ghost>
                  <Anchor component={Link} to="/triage" size="sm" mt={6}>
                    {t('home.active_blocks.view_all', { count: total })}
                  </Anchor>
                </Ghost>
              )}
            </Stack>
          )}
        </Stack>
      </Card>
    </GhostScope>
  );
}
