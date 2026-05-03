import { Group, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { TriageBucket } from '../lib/bucketLabels';

export interface FinalizeSummaryRowProps {
  bucket: TriageBucket;
}

export function FinalizeSummaryRow({ bucket }: FinalizeSummaryRowProps) {
  const { t } = useTranslation();
  return (
    <Group
      justify="space-between"
      wrap="nowrap"
      style={{
        padding: 'var(--mantine-spacing-xs) 0',
        borderBottom: '1px solid var(--color-border)',
      }}
    >
      <Text>{bucket.category_name ?? '—'}</Text>
      <Text className="font-mono" c="dimmed">
        +{t('triage.finalize.confirm.row_count', { count: bucket.track_count })}
      </Text>
    </Group>
  );
}
