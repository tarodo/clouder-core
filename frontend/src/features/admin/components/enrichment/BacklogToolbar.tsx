import { Group, Select, Text, Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { LabelStatusFilter } from '../../hooks/useLabelBacklog';

export interface StyleFilterOption {
  /** Slug form used as the API filter value, e.g. "drum-and-bass". */
  value: string;
  /** Display label, e.g. "Drum & Bass". */
  label: string;
}

interface Props {
  style: string;
  onStyleChange: (style: string) => void;
  status: LabelStatusFilter;
  onStatusChange: (s: LabelStatusFilter) => void;
  selectedCount: number;
  onEnqueueClick: () => void;
  styleOptions: ReadonlyArray<StyleFilterOption>;
  stylesLoading?: boolean;
}

export function BacklogToolbar(p: Props) {
  const { t } = useTranslation();
  const styleData = [{ value: '', label: 'all' }, ...p.styleOptions];
  return (
    <Group justify="space-between">
      <Group gap="sm">
        <Select
          label={t('admin_enrichment.backlog.filter_style')}
          value={p.style}
          onChange={(v) => v != null && p.onStyleChange(v)}
          data={styleData}
          disabled={p.stylesLoading}
        />
        <Select
          label={t('admin_enrichment.backlog.filter_status')}
          value={p.status}
          onChange={(v) => v && p.onStatusChange(v as LabelStatusFilter)}
          data={[
            { value: 'all', label: t('admin_enrichment.backlog.status_all') },
            { value: 'none', label: t('admin_enrichment.backlog.status_none') },
            { value: 'completed', label: t('admin_enrichment.backlog.status_completed') },
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
