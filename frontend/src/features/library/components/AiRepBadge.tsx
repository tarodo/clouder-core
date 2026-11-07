import { Badge, Text, Tooltip, type MantineColor, type TextProps } from '@mantine/core';
import { createContext, useContext, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import classes from './NameLine.module.css';

/** A label's / an artist's AI reputation from the API: level 1 = at least one flagged track,
 * 2 = 25-50% of the checked ones, 3 = over half. */
export type AiRep = { level: 1 | 2 | 3; ai: number; checked: number; total: number };

// Monochrome, so it never reads as a track's own coloured AI badge (owner's mockups, 2026-10-29).
const LOOK: Record<AiRep['level'], { bg: string; fg: string; bd: string }> = {
  1: { bg: '#fff', fg: '#000', bd: '#000' },
  2: { bg: '#6b6b6b', fg: '#fff', bd: '#6b6b6b' },
  3: { bg: '#000', fg: '#fff', bd: '#000' },
};

export function AiRepBadge({ rep, ml }: { rep?: AiRep | null; ml?: number }) {
  const { t } = useTranslation();
  if (!rep) return null;
  const look = LOOK[rep.level];
  return (
    <Tooltip
      label={t('library.ai_rep.tooltip', {
        ai: rep.ai.toLocaleString(),
        checked: rep.checked.toLocaleString(),
        total: rep.total.toLocaleString(),
      })}
      events={{ hover: true, focus: true, touch: true }}
      withArrow
    >
      <Badge
        size="xs"
        radius="sm"
        tabIndex={0}
        data-level={rep.level}
        aria-label={t('library.ai_rep.aria', { level: rep.level })}
        ml={ml}
        styles={{
          root: {
            background: look.bg,
            color: look.fg,
            border: `1px solid ${look.bd}`,
            flexShrink: 0,
            cursor: 'default',
            verticalAlign: 'middle',
          },
        }}
      >
        AI
      </Badge>
    </Tooltip>
  );
}

const InNameLine = createContext(false);

/** A name followed by its AI badge. Plain running text, except inside a `NameLine`: there the name
 * gets its own box, which is what ends in an ellipsis, so the badge never goes with the tail. */
export function NameWithAi({
  name,
  ai,
  c,
}: {
  name: ReactNode;
  ai?: AiRep | null;
  c?: MantineColor;
}) {
  const boxed = useContext(InNameLine) || c;
  return (
    <>
      {boxed ? (
        <Text span inherit c={c} data-name>
          {name}
        </Text>
      ) : (
        name
      )}
      <AiRepBadge rep={ai} ml={4} />
    </>
  );
}

/** A one-line, never-wrapping run of `NameWithAi`s: where `Text truncate` would cut the badges
 * off with the tail, here each name shrinks and the badges stay. */
export function NameLine({ children, ...props }: TextProps & { children: ReactNode }) {
  return (
    <Text component="div" {...props} className={classes.line}>
      <InNameLine.Provider value>{children}</InNameLine.Provider>
    </Text>
  );
}

/** Comma-joined names, each followed by its AI badge; a dash when there are none. */
export function NamesWithAi({
  items,
}: {
  items: ReadonlyArray<{ name: string; ai?: AiRep | null }>;
}) {
  if (items.length === 0) return <>—</>;
  return (
    <>
      {items.map((it, i) => (
        <NameWithAi key={i} name={i > 0 ? `, ${it.name}` : it.name} ai={it.ai} />
      ))}
    </>
  );
}
