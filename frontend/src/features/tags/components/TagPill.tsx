import { Box, type BoxProps } from '@mantine/core';
import { softTagColors } from '../lib/tagPalette';

export interface TagPillProps extends BoxProps {
  name: string;
  color: string | null;
  /**
   * When set, the whole pill becomes a clickable toggle that emits `onRemove`
   * (no separate `×` icon — the coloured pill itself is the affordance).
   */
  onRemove?: () => void;
}

export function TagPill({ name, color, onRemove, ...rest }: TagPillProps) {
  const { bg, fg, border } = softTagColors(color);
  const interactive = !!onRemove;
  return (
    <Box
      component="span"
      px={8}
      py={2}
      {...(interactive
        ? {
            role: 'button',
            tabIndex: 0,
            'aria-label': `Remove ${name}`,
            onClick: onRemove,
            onKeyDown: (e: React.KeyboardEvent) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onRemove?.();
              }
            },
          }
        : {})}
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
        // Makes 1- and 2-char tags one width; longer tags grow. Update if px/border changes.
        minWidth: 'calc(2ch + 18px)',
        backgroundColor: bg,
        color: fg,
        border: `1px solid ${border}`,
        cursor: interactive ? 'pointer' : undefined,
      }}
      {...rest}
    >
      <span>{name}</span>
    </Box>
  );
}
