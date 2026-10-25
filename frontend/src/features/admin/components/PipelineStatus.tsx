import { Badge, Box, Group, Paper, Progress, SimpleGrid, Stack, Text } from '@mantine/core';
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { api } from '../../../api/client';
import type { components } from '../../../api/schema';
import { AiBadge } from '../../playback/AiBadge';

dayjs.extend(relativeTime);

type Spotify = components['schemas']['SpotifySearchStatus'];
type Youtube = components['schemas']['YoutubeSearchStatus'];
type Analysis = components['schemas']['AnalysisStatus'];

// TanStack Query v5 skips interval refetches while the tab is hidden, so an idle
// admin tab does not keep Aurora awake.
const POLL_MS = 30_000;
// The analyzer calls in every few minutes while it runs; days of silence mean it is off.
const STALE_DAYS = 3;

const SEARCH_COLOR: Record<Youtube['status'], string> = {
  running: 'green',
  queued: 'blue',
  paused: 'orange',
  idle: 'gray',
};

const fmt = (n: number) => n.toLocaleString('en-US');

function pct(n: number, of: number): string {
  if (!of) return '—';
  const p = (n / of) * 100;
  return n > 0 && p < 0.1 ? '<0.1%' : `${p.toFixed(1)}%`;
}

/** A slice of a stage's total. `open` slices (in progress, waiting) are not done yet; a slice
 * without a color stays out of the bar. Colors are Mantine theme colors, `name` or `name.shade`. */
type Bucket = { label: string; value: number; color?: string; marker?: ReactNode; open?: boolean };

const cssColor = (color: string) => {
  const [name, shade] = color.split('.');
  return `var(--mantine-color-${name}-${shade ?? 'filled'})`;
};

function Swatch({ color }: { color?: string }) {
  return (
    <Box
      w={10}
      h={10}
      style={{
        borderRadius: '50%',
        background: color ? cssColor(color) : undefined,
        border: color ? undefined : '1px solid var(--mantine-color-dimmed)',
      }}
    />
  );
}

/** One funnel stage: its buckets split `total` exactly, so the rows always add up. */
function Stage(props: {
  title: string;
  status?: ReactNode;
  total: number;
  doneLabel: string;
  base: string;
  buckets: Bucket[];
  children?: ReactNode;
}) {
  const { title, status, total, doneLabel, base, buckets, children } = props;
  const done = total - buckets.filter((b) => b.open).reduce((sum, b) => sum + b.value, 0);
  return (
    <Paper withBorder p="md" radius="md" data-stage={title}>
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap" mih={22}>
          <Text fw={600}>{title}</Text>
          {status}
        </Group>
        <div>
          <Group gap={6} align="baseline">
            <Text fw={700} size="xl" lh={1.2}>
              {fmt(done)}
            </Text>
            <Text size="sm" c="dimmed">
              / {fmt(total)}
            </Text>
          </Group>
          <Text size="xs" c="dimmed">
            {doneLabel} · {pct(done, total)} {base}
          </Text>
        </div>
        <Progress.Root size="sm">
          {buckets
            .filter((b) => b.color && b.value > 0)
            .map((b) => (
              <Progress.Section key={b.label} value={(b.value / total) * 100} color={b.color} />
            ))}
        </Progress.Root>
        <Stack gap={2}>
          {buckets.map((b) => (
            <Group key={b.label} justify="space-between" wrap="nowrap" data-bucket={b.label}>
              <Group gap={4} wrap="nowrap">
                {/* one marker column: an AI badge is wider than a swatch */}
                <Box w={24} style={{ display: 'flex', flexShrink: 0 }}>
                  {b.marker ?? <Swatch color={b.color} />}
                </Box>
                <Text size="sm">{b.label}</Text>
              </Group>
              <Group gap="xs" wrap="nowrap">
                <Text size="sm" fw={600}>
                  {fmt(b.value)}
                </Text>
                <Text size="xs" c="dimmed" w={44} ta="right">
                  {pct(b.value, total)}
                </Text>
              </Group>
            </Group>
          ))}
        </Stack>
        {children && <Stack gap={2}>{children}</Stack>}
      </Stack>
    </Paper>
  );
}

function Note({ children }: { children: ReactNode }) {
  return (
    <Text size="xs" c="dimmed">
      {children}
    </Text>
  );
}

function SearchBadge({ data }: { data: Spotify | Youtube }) {
  const { t } = useTranslation();
  const label =
    data.status === 'paused' && data.paused_until
      ? t('admin.pipeline.paused_until', {
          time: new Date(data.paused_until).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          }),
        })
      : t(`admin.pipeline.${data.status}`);
  return (
    <Badge color={SEARCH_COLOR[data.status]} variant="light">
      {label}
    </Badge>
  );
}

function AnalyzerBadge({ data }: { data: Analysis }) {
  const { t } = useTranslation();
  const last = data.last_claim_at ? dayjs(data.last_claim_at) : null;
  const silentDays = last ? dayjs().diff(last, 'day') : null;
  const [color, label] =
    last === null
      ? ['gray', t('admin.pipeline.never')]
      : silentDays !== null && silentDays >= STALE_DAYS
        ? ['orange', t('admin.pipeline.stale', { days: silentDays })]
        : ['green', t('admin.pipeline.last_run', { ago: last.fromNow() })];
  return (
    <Badge color={color} variant="light">
      {label}
    </Badge>
  );
}

const MODELS = [
  ['ai_lofcz', 'lofcz'],
  ['ai_deezer', 'Deezer'],
] as const;

/** Admin funnel: the Beatport catalog → Spotify and YouTube search → AI detection and the
 * audio profile on the YT Music matches. Each stage splits its base, so YT Music "Matched"
 * is the total of both stages after it. */
export function PipelineStatus() {
  const { t } = useTranslation();
  const spotify = useQuery({
    queryKey: ['admin', 'spotifySearchStatus'],
    queryFn: () => api<Spotify>('/admin/spotify/search-status'),
    refetchInterval: POLL_MS,
  });
  const youtube = useQuery({
    queryKey: ['admin', 'youtubeSearchStatus'],
    queryFn: () => api<Youtube>('/admin/youtube/search-status'),
    refetchInterval: POLL_MS,
  });
  const analysis = useQuery({
    queryKey: ['admin', 'analysisStatus'],
    queryFn: () => api<Analysis>('/admin/analysis/status'),
    refetchInterval: POLL_MS,
  });
  const p = (key: string, opts?: Record<string, unknown>) => t(`admin.pipeline.${key}`, opts);
  const catalog = youtube.data?.tracks.total ?? spotify.data?.tracks.total;
  const sp = spotify.data;
  const yt = youtube.data;
  const an = analysis.data;

  return (
    <Stack gap="sm">
      <Group gap="xs" align="baseline">
        <Text fw={600}>{p('title')}</Text>
        {catalog !== undefined && (
          <Text size="sm" c="dimmed">
            {p('catalog', { count: fmt(catalog) })}
          </Text>
        )}
      </Group>
      <SimpleGrid type="container" cols={{ base: 1, '560px': 2, '1100px': 4 }}>
        {sp && (
          <Stage
            title="Spotify"
            status={<SearchBadge data={sp} />}
            total={sp.tracks.total}
            doneLabel={p('searched')}
            base={p('of_catalog')}
            buckets={[
              { label: p('found'), value: sp.tracks.found, color: 'teal' },
              { label: p('not_found'), value: sp.tracks.not_found, color: 'gray.5' },
              { label: p('no_isrc'), value: sp.tracks.no_isrc, color: 'gray.8' },
              { label: p('waiting'), value: sp.tracks.waiting, open: true },
            ]}
          >
            <Note>{p('recent', { count: fmt(sp.tracks.searched_last_10_min) })}</Note>
          </Stage>
        )}
        {yt && (
          <Stage
            title="YouTube Music"
            status={<SearchBadge data={yt} />}
            total={yt.tracks.total}
            doneLabel={p('searched')}
            base={p('of_catalog')}
            buckets={[
              { label: p('matched'), value: yt.results.matched, color: 'teal' },
              { label: p('needs_review'), value: yt.results.needs_review, color: 'grape' },
              { label: p('not_on_yt'), value: yt.results.not_found, color: 'gray.5' },
              { label: p('error'), value: yt.results.error, color: 'red' },
              { label: p('waiting'), value: yt.tracks.waiting, open: true },
            ]}
          >
            <Note>{p('videos', { count: fmt(yt.results.videos) })}</Note>
            <Note>{p('recent', { count: fmt(yt.tracks.searched_last_10_min) })}</Note>
          </Stage>
        )}
        {an && (
          <Stage
            title={p('ai')}
            status={<AnalyzerBadge data={an} />}
            total={an.queue.total}
            doneLabel={p('checked')}
            base={p('of_matches')}
            buckets={[
              ...(['high', 'medium', 'low'] as const).map((level) => ({
                label: p(`level_${level}`),
                value: an.pair[level],
                color: { high: 'red', medium: 'orange', low: 'yellow' }[level],
                marker: <AiBadge verdict={level} />,
              })),
              { label: p('clean'), value: an.pair.clean, color: 'teal' },
              { label: p('unavailable'), value: an.queue.failed, color: 'gray.5' },
              { label: p('unusable'), value: an.queue.unusable, color: 'gray.8' },
              { label: p('in_progress'), value: an.queue.in_progress, color: 'blue', open: true },
              { label: p('waiting'), value: an.queue.waiting, open: true },
            ]}
          >
            <AiSummary data={an} />
          </Stage>
        )}
        {an && (
          <Stage
            title={p('profile')}
            total={an.profile.total}
            doneLabel={p('profiled')}
            base={p('of_matches')}
            buckets={[
              { label: p('profiled_bucket'), value: an.profile.profiled, color: 'teal' },
              { label: p('unavailable'), value: an.profile.failed, color: 'gray.5' },
              { label: p('unusable'), value: an.profile.unusable, color: 'gray.8' },
              { label: p('in_progress'), value: an.profile.in_progress, color: 'blue', open: true },
              { label: p('waiting'), value: an.profile.waiting, open: true },
            ]}
          >
            <Note>
              {an.models.count > 0 && an.models.last_trained_at
                ? p('models', {
                    count: an.models.count,
                    ago: dayjs(an.models.last_trained_at).fromNow(),
                  })
                : p('models_none')}
            </Note>
          </Stage>
        )}
      </SimpleGrid>
    </Stack>
  );
}

/** The AI share of the verdicts, each detector on its own, and when results last came in. */
function AiSummary({ data }: { data: Analysis }) {
  const { t } = useTranslation();
  const { high, medium, low, clean } = data.pair;
  const ai = high + medium + low;
  return (
    <>
      <Note>{t('admin.pipeline.ai_share', { count: fmt(ai), pct: pct(ai, ai + clean) })}</Note>
      {MODELS.map(([name, label]) => {
        const row = data.analyzers.find((a) => a.name === name);
        return (
          row && (
            <Note key={name}>
              {t('admin.pipeline.model', {
                name: label,
                ai: fmt(row.ai_detected),
                clean: fmt(row.ok - row.ai_detected),
              })}
            </Note>
          )
        );
      })}
      {data.last_claim_at && (
        <Note>
          {data.last_result_at
            ? t('admin.pipeline.last_result', { ago: dayjs(data.last_result_at).fromNow() })
            : t('admin.pipeline.no_results')}
        </Note>
      )}
    </>
  );
}
