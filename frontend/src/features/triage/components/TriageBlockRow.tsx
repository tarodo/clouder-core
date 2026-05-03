import { ActionIcon, Badge, Group, Menu, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { IconDotsVertical, IconTrash } from '../../../components/icons';
import type { TriageBlockSummary } from '../hooks/useTriageBlocksByStyle';

export interface TriageBlockRowProps {
  block: TriageBlockSummary;
  styleId: string;
  onDelete: (block: TriageBlockSummary) => void;
  timeField?: 'created_at' | 'finalized_at';
}

export function TriageBlockRow({
  block,
  styleId,
  onDelete,
  timeField = 'created_at',
}: TriageBlockRowProps) {
  const { t } = useTranslation();
  const time = timeField === 'finalized_at' ? block.finalized_at : block.created_at;

  return (
    <Group
      justify="space-between"
      wrap="nowrap"
      px="md"
      py="sm"
      style={{
        borderBottom: '1px solid var(--color-border)',
      }}
    >
      <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
        <Text
          component={Link}
          to={`/triage/${styleId}/${block.id}`}
          c="var(--color-fg)"
          td="none"
          fw={500}
          truncate
        >
          {block.name}
        </Text>
        <Group gap="md" wrap="nowrap">
          <Text size="sm" ff="var(--font-mono)" c="var(--color-fg-muted)">
            {t('triage.row.date_range', {
              from: block.date_from,
              to: block.date_to,
            })}
          </Text>
          {time && (
            <Text size="sm" c="var(--color-fg-muted)">
              {time.slice(0, 10)}
            </Text>
          )}
        </Group>
      </Stack>
      <Group gap="sm" wrap="nowrap">
        <Badge variant="light" radius="sm">
          {t('triage.track_count', { count: block.track_count })}
        </Badge>
        <Menu position="bottom-end" withinPortal={false} transitionProps={{ duration: 0 }}>
          <Menu.Target>
            <ActionIcon
              variant="subtle"
              aria-label="menu"
              color="gray"
              size="md"
            >
              <IconDotsVertical size={18} />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item
              leftSection={<IconTrash size={14} />}
              color="red"
              onClick={() => onDelete(block)}
            >
              {t('triage.row.menu.delete')}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>
    </Group>
  );
}
