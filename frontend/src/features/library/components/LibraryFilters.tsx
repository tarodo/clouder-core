import { Group, TextInput, Select, SegmentedControl, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useState, useEffect } from 'react';
import type { LabelsListMy } from '../hooks/useLabelsList';

export interface StyleOption {
  value: string;
  label: string;
}

interface Props {
  q: string;
  sort: 'name' | 'recent';
  styleId: string;
  styleOptions: ReadonlyArray<StyleOption>;
  stylesLoading?: boolean;
  my: LabelsListMy;
  onQChange: (q: string) => void;
  onSortChange: (sort: 'name' | 'recent') => void;
  onStyleChange: (styleId: string) => void;
  onMyChange: (my: LabelsListMy) => void;
  hideMyFilter?: boolean;
}

export function LibraryFilters({
  q,
  sort,
  styleId,
  styleOptions,
  stylesLoading,
  my,
  onQChange,
  onSortChange,
  onStyleChange,
  onMyChange,
  hideMyFilter = false,
}: Props) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(q);

  useEffect(() => setDraft(q), [q]);
  useEffect(() => {
    const id = setTimeout(() => {
      if (draft !== q) onQChange(draft);
    }, 250);
    return () => clearTimeout(id);
  }, [draft, q, onQChange]);

  return (
    <Group gap="sm" align="end" wrap="wrap">
      <Select
        label={t('library.list.style_label')}
        value={styleId}
        onChange={(v) => v && onStyleChange(v)}
        data={styleOptions as StyleOption[]}
        disabled={stylesLoading}
        miw={200}
      />
      <TextInput
        label={t('library.list.search_label')}
        placeholder={t('library.list.search_placeholder')}
        value={draft}
        onChange={(e) => setDraft(e.currentTarget.value)}
        miw={240}
        style={{ flex: 1 }}
      />
      <Select
        label={t('library.list.sort_label')}
        value={sort}
        data={[
          { value: 'name', label: t('library.list.sort_name') },
          { value: 'recent', label: t('library.list.sort_recent') },
        ]}
        onChange={(v) => v && onSortChange(v as 'name' | 'recent')}
        miw={180}
      />
      {!hideMyFilter && (
        <Stack gap={4}>
          <Text size="xs" c="dimmed">
            {t('library.list.my_filter_label')}
          </Text>
          <SegmentedControl
            value={my}
            onChange={(v) => onMyChange(v as LabelsListMy)}
            data={[
              { value: 'all', label: t('library.list.my_all') },
              { value: 'liked', label: t('library.list.my_liked') },
              { value: 'disliked', label: t('library.list.my_disliked') },
              { value: 'unrated', label: t('library.list.my_unrated') },
            ]}
          />
        </Stack>
      )}
    </Group>
  );
}
