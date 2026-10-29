import { Badge, Tooltip } from '@mantine/core';
import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';

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
        <Fragment key={i}>
          {i > 0 && ', '}
          {it.name}
          <AiRepBadge rep={it.ai} ml={4} />
        </Fragment>
      ))}
    </>
  );
}
