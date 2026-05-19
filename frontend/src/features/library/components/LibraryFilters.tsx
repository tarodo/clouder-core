import { Group, TextInput, Select } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useState, useEffect } from 'react';

interface Props {
  q: string;
  sort: 'name' | 'recent';
  onQChange: (q: string) => void;
  onSortChange: (sort: 'name' | 'recent') => void;
}

export function LibraryFilters({ q, sort, onQChange, onSortChange }: Props) {
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
    <Group gap="sm">
      <TextInput
        placeholder={t('library.list.search_placeholder')}
        value={draft}
        onChange={(e) => setDraft(e.currentTarget.value)}
        style={{ minWidth: 240 }}
      />
      <Select
        label={t('library.list.sort_label')}
        value={sort}
        data={[
          { value: 'name', label: t('library.list.sort_name') },
          { value: 'recent', label: t('library.list.sort_recent') },
        ]}
        onChange={(v) => v && onSortChange(v as 'name' | 'recent')}
      />
    </Group>
  );
}
