import { Group, TextInput, Select } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useState, useEffect } from 'react';

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
  onQChange: (q: string) => void;
  onSortChange: (sort: 'name' | 'recent') => void;
  onStyleChange: (styleId: string) => void;
}

export function LibraryFilters({
  q,
  sort,
  styleId,
  styleOptions,
  stylesLoading,
  onQChange,
  onSortChange,
  onStyleChange,
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
        style={{ minWidth: 200 }}
      />
      <TextInput
        label={t('library.list.search_label')}
        placeholder={t('library.list.search_placeholder')}
        value={draft}
        onChange={(e) => setDraft(e.currentTarget.value)}
        style={{ minWidth: 240, flex: 1 }}
      />
      <Select
        label={t('library.list.sort_label')}
        value={sort}
        data={[
          { value: 'name', label: t('library.list.sort_name') },
          { value: 'recent', label: t('library.list.sort_recent') },
        ]}
        onChange={(v) => v && onSortChange(v as 'name' | 'recent')}
        style={{ minWidth: 180 }}
      />
    </Group>
  );
}
