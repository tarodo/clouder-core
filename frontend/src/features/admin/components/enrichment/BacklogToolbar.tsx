import { Group, Select, Text, Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export interface StyleFilterOption {
  /** Slug form used as the API filter value, e.g. "drum-and-bass". */
  value: string;
  /** Display label, e.g. "Drum & Bass". */
  label: string;
}

interface Props {
  style: string;
  onStyleChange: (style: string) => void;
  status: 'all' | 'none' | 'failed' | 'outdated';
  onStatusChange: (s: 'all' | 'none' | 'failed' | 'outdated') => void;
  selectedCount: number;
  onEnqueueClick: () => void;
  styleOptions: ReadonlyArray<StyleFilterOption>;
  stylesLoading?: boolean;
}

export function BacklogToolbar(p: Props) {
  const { t } = useTranslation();
  const data = [{ value: '', label: 'all' }, ...p.styleOptions];
  return (
    <Group justify="space-between">
      <Group gap="sm">
        <Select
          label={t('admin_enrichment.backlog.filter_style')}
          value={p.style}
          onChange={(v) => v != null && p.onStyleChange(v)}
          data={data}
          disabled={p.stylesLoading}
        />
        <Select
          label={t('admin_enrichment.backlog.filter_status')}
          value={p.status}
          onChange={(v) => v && p.onStatusChange(v as Props['status'])}
          data={[
            { value: 'all', label: 'all' },
            { value: 'none', label: t('admin_enrichment.backlog.status_none') },
            { value: 'failed', label: t('admin_enrichment.backlog.status_failed') },
            { value: 'outdated', label: t('admin_enrichment.backlog.status_outdated') },
          ]}
        />
      </Group>
      <Group gap="sm">
        <Text size="sm" c="dimmed">
          {t('admin_enrichment.backlog.selected_summary', { count: p.selectedCount })}
        </Text>
        <Button onClick={p.onEnqueueClick} disabled={p.selectedCount === 0}>
          {t('admin_enrichment.backlog.enqueue_button', { count: p.selectedCount })}
        </Button>
      </Group>
    </Group>
  );
}
