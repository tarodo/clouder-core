import { Box, type BoxProps } from '@mantine/core';
import { pickPillTextColor } from '../lib/tagPalette';

export interface TagPillProps extends BoxProps {
  name: string;
  color: string | null;
  /** Render an additional `×` to the right; emits `onRemove` when clicked. */
  onRemove?: () => void;
}

export function TagPill({ name, color, onRemove, ...rest }: TagPillProps) {
  const fg = pickPillTextColor(color);
  const baseStyle: React.CSSProperties = color
    ? {
        backgroundColor: color,
        color: fg,
        border: '1px solid transparent',
      }
    : {
        backgroundColor: 'transparent',
        color: 'var(--mantine-color-text)',
        border: '1px solid var(--mantine-color-default-border)',
        borderStyle: 'solid',
      };
  return (
    <Box
      component="span"
      px={8}
      py={2}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        borderRadius: 999,
        fontSize: 12,
        lineHeight: 1.4,
        ...baseStyle,
      }}
      {...rest}
    >
      <span>{name}</span>
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          aria-label={`Remove ${name}`}
          style={{
            all: 'unset',
            cursor: 'pointer',
            opacity: 0.7,
            fontSize: 12,
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </Box>
  );
}
