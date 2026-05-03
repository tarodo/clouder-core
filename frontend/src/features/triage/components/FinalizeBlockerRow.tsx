import { Anchor, Group, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';

export interface FinalizeBlockerRowProps {
  categoryName: string;
  trackCount: number;
  href: string;
  onNavigate: () => void;
}

export function FinalizeBlockerRow({
  categoryName,
  trackCount,
  href,
  onNavigate,
}: FinalizeBlockerRowProps) {
  const { t } = useTranslation();
  return (
    <Group
      justify="space-between"
      wrap="nowrap"
      style={{
        padding: 'var(--mantine-spacing-sm)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-md)',
      }}
    >
      <Stack gap={2}>
        <Text fw={500}>{categoryName}</Text>
        <Text size="sm" c="dimmed">
          {t('triage.finalize.blocker.row_count', { count: trackCount })}
        </Text>
      </Stack>
      <Anchor component={Link} to={href} onClick={onNavigate}>
        {t('triage.finalize.blocker.open')}
      </Anchor>
    </Group>
  );
}
