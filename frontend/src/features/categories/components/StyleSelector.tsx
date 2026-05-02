import { Select } from '@mantine/core';
import { useStyles } from '../../../hooks/useStyles';

export interface StyleSelectorProps {
  value: string;
  onChange: (styleId: string) => void;
}

export function StyleSelector({ value, onChange }: StyleSelectorProps) {
  const { data, isLoading } = useStyles();
  const items = data?.items ?? [];
  return (
    <Select
      data={items.map((s) => ({ value: s.id, label: s.name }))}
      value={value}
      onChange={(v) => v && onChange(v)}
      disabled={isLoading || items.length === 0}
      allowDeselect={false}
      searchable
      maxDropdownHeight={300}
      w={220}
    />
  );
}
