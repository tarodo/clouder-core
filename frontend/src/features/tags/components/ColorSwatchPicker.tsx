import { Group, UnstyledButton, ColorSwatch } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { TAG_PALETTE } from '../lib/tagPalette';

export interface ColorSwatchPickerProps {
  value: string | null;
  onChange: (next: string | null) => void;
}

export function ColorSwatchPicker({ value, onChange }: ColorSwatchPickerProps) {
  const { t } = useTranslation();
  return (
    <Group gap={6} wrap="wrap">
      {TAG_PALETTE.map((c) => {
        const active = value?.toLowerCase() === c.toLowerCase();
        return (
          <UnstyledButton
            key={c}
            type="button"
            onClick={() => onChange(c)}
            aria-label={`colour ${c}`}
            aria-pressed={active}
            style={{
              borderRadius: 999,
              outline: active ? '2px solid var(--mantine-color-text)' : 'none',
              outlineOffset: 1,
            }}
          >
            <ColorSwatch color={c} size={20} />
          </UnstyledButton>
        );
      })}
      <UnstyledButton
        type="button"
        onClick={() => onChange(null)}
        aria-label={t('tags.color_picker.none_aria')}
        aria-pressed={value === null}
        style={{
          width: 20,
          height: 20,
          border: '1px solid var(--mantine-color-default-border)',
          borderRadius: 999,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 14,
          lineHeight: 1,
          outline: value === null ? '2px solid var(--mantine-color-text)' : 'none',
          outlineOffset: 1,
        }}
      >
        ×
      </UnstyledButton>
    </Group>
  );
}
