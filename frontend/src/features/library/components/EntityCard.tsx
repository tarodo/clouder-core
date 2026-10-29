import { Anchor, Box, Group, Paper, Stack, Text } from '@mantine/core';
import { Fragment, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Ghost, GhostScope } from '../../../components/Ghost';
import { AiRepBadge, type AiRep } from './AiRepBadge';

/** A label's / an artist's catalog tracks, and how many of them the user kept in categories and
 * playlists (`stats` of GET /labels/{id}, /artists/{id}). */
export interface EntityStats {
  tracks: number;
  in_categories: number;
  in_playlists: number;
}

const GHOST_STATS: EntityStats = { tracks: 100, in_categories: 10, in_playlists: 1 };

/** The numbers as a column: a figure (right-aligned, monospace) and what it counts. It reads the
 * same in the curate panel's narrow column and in the 442px player panels. */
function Stats({ rows }: { rows: [number, string][] }) {
  return (
    <Box
      style={{
        display: 'grid',
        gridTemplateColumns: 'auto 1fr',
        columnGap: 8,
        alignItems: 'baseline',
      }}
    >
      {rows.map(([value, label]) => (
        <Fragment key={label}>
          <Ghost>
            <Text size="sm" fw={600} ff="monospace" ta="right" c={value ? undefined : 'dimmed'}>
              {value.toLocaleString('en-US')}
            </Text>
          </Ghost>
          <Text size="xs" c="dimmed">
            {label}
          </Text>
        </Fragment>
      ))}
    </Box>
  );
}

/** Long text, four lines and a More / Less switch. */
export function Clamped({ text }: { text: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const long = text.length > 220;
  return (
    <Stack gap={2} align="flex-start">
      <Text size="sm" className="prewrap" lineClamp={open || !long ? undefined : 4}>
        {text}
      </Text>
      {long && (
        <Anchor component="button" type="button" size="xs" onClick={() => setOpen(!open)}>
          {t(open ? 'library.entity.less' : 'library.entity.more')}
        </Anchor>
      )}
    </Stack>
  );
}

/** The player's label / artist card: the role and like / dislike on one line, the name, the
 * user's numbers, then what the info search found (or that it found nothing yet). Every card
 * looks the same, however many artists a track has. */
export function EntityCard(props: {
  role: string;
  name: string;
  href: string;
  ai?: AiRep | null;
  preferences: ReactNode;
  /** undefined while the detail loads: the numbers and the info are a ghost. */
  stats: EntityStats | undefined;
  /** The info search found something; `children` shows it. */
  hasInfo: boolean;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const loading = props.stats === undefined;
  const stats = props.stats ?? GHOST_STATS;
  return (
    <Paper withBorder radius="md" p="sm" maw={320} data-entity={props.role}>
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap" gap="xs" mih={28}>
          <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
            {props.role}
          </Text>
          {props.preferences}
        </Group>
        <Group gap={6} wrap="nowrap" align="center" mt={-6}>
          <Anchor
            component={Link}
            to={props.href}
            fw={600}
            size="md"
            c="inherit"
            lineClamp={2}
            style={{ minWidth: 0 }}
          >
            {props.name}
          </Anchor>
          <AiRepBadge rep={props.ai} />
        </Group>
        <GhostScope on={loading}>
          <Stats
            rows={[
              [stats.tracks, t('library.entity.in_clouder')],
              [stats.in_categories, t('library.entity.in_categories')],
              [stats.in_playlists, t('library.entity.in_playlists')],
            ]}
          />
          {loading ? (
            <Ghost block>
              <Text size="sm">{t('library.entity.no_info')}</Text>
            </Ghost>
          ) : props.hasInfo ? (
            props.children
          ) : (
            <Text size="xs" c="dimmed">
              {t('library.entity.no_info')}
            </Text>
          )}
        </GhostScope>
      </Stack>
    </Paper>
  );
}
