import { Group, MultiSelect, SegmentedControl, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useTags } from '../hooks/useTags';
import type { TagsFilterState } from '../lib/tagsUrlState';

export interface TagsFilterBarProps {
  selectedIds: string[];
  match: 'all' | 'any';
  onChange: (next: TagsFilterState) => void;
}

export function TagsFilterBar({ selectedIds, match, onChange }: TagsFilterBarProps) {
  const { t } = useTranslation();
  const tagsQ = useTags();
  const data = (tagsQ.data ?? []).map((tag) => ({
    value: tag.id,
    label: tag.name,
  }));

  return (
    <Group gap="sm" wrap="wrap" align="center">
      <MultiSelect
        placeholder={t('tags.filter.placeholder')}
        data={data}
        value={selectedIds}
        onChange={(next) => onChange({ selectedIds: next, match })}
        searchable
        clearable
        nothingFoundMessage={t('tags.filter.empty')}
        style={{ minWidth: 220 }}
      />
      {selectedIds.length > 0 && (
        <SegmentedControl
          value={match}
          onChange={(value) =>
            onChange({ selectedIds, match: value === 'any' ? 'any' : 'all' })
          }
          data={[
            { value: 'all', label: t('tags.filter.match_all') },
            { value: 'any', label: t('tags.filter.match_any') },
          ]}
          size="xs"
        />
      )}
      {selectedIds.length > 0 && (
        <Text size="xs" c="dimmed">
          {t('tags.filter.count', { count: selectedIds.length })}
        </Text>
      )}
    </Group>
  );
}
