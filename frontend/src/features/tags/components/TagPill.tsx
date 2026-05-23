import { Box, type BoxProps } from '@mantine/core';
import { softTagColors } from '../lib/tagPalette';

export interface TagPillProps extends BoxProps {
  name: string;
  color: string | null;
  /** Render an additional `×` to the right; emits `onRemove` when clicked. */
  onRemove?: () => void;
}

export function TagPill({ name, color, onRemove, ...rest }: TagPillProps) {
  const { bg, fg, border } = softTagColors(color);
  return (
    <Box
      component="span"
      px={8}
      py={2}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 4,
        borderRadius: 999,
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        lineHeight: 1.4,
        // 2ch content + px×2 (8px) + border×2 (1px), box-sizing: border-box.
        // Makes 1- and 2-char tags one width; longer tags grow. Update if px/border change.
        minWidth: 'calc(2ch + 18px)',
        backgroundColor: bg,
        color: fg,
        border: `1px solid ${border}`,
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
