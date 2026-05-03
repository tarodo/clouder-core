import { Stack, Text, UnstyledButton } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { TriageBlockSummary } from '../hooks/useTriageBlocksByStyle';

export interface TransferBlockOptionProps {
  block: TriageBlockSummary;
  onSelect: () => void;
}

export function TransferBlockOption({ block, onSelect }: TransferBlockOptionProps) {
  const { t } = useTranslation();
  return (
    <UnstyledButton
      onClick={onSelect}
      style={{
        display: 'block',
        width: '100%',
        padding: 'var(--mantine-spacing-md)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--mantine-radius-md)',
      }}
    >
      <Stack gap={2}>
        <Text fw={600}>{block.name}</Text>
        <Text size="sm" c="dimmed">
          {block.date_from} → {block.date_to} ·{' '}
          {t('triage.transfer.modal.track_count', { count: block.track_count })}
        </Text>
      </Stack>
    </UnstyledButton>
  );
}
