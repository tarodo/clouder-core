import { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconInfoCircle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import type { AutoIngestSettingsBody, AutoIngestState } from '../../../api/autoIngest';
import { useAutoIngest } from '../hooks/useAutoIngest';
import { useSaveAutoIngest } from '../hooks/useSaveAutoIngest';
import { useRunAutoIngest } from '../hooks/useRunAutoIngest';
import { Note, StatCard } from './StatCard';

dayjs.extend(relativeTime);

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

interface Form {
  enabled: boolean;
  mode: 'fixed' | 'random';
  times: string;
  runsPerDay: number | string;
  timezone: string;
  periodsPerRun: number | string;
  floor: string;
}

function parseTimes(raw: string): string[] {
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

function timesValid(times: string[]): boolean {
  return (
    times.length >= 1 &&
    times.length <= 12 &&
    times.every((t) => HHMM.test(t)) &&
    new Set(times).size === times.length
  );
}

function intIn(value: number | string, min: number, max: number): number | null {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isInteger(n) && n >= min && n <= max ? n : null;
}

function week(y: number, n: number): string {
  return `${y}-W${n}`;
}

const today = () => new Date().toISOString().slice(0, 10);

const fmt = (n: number) => n.toLocaleString('en-US');

/** The planner's next run: daily at 00:05 UTC it plans the runs up to the one after
 * (auto_ingest_schedule.PLANNER_AT), so after the day's last run nothing is planned until then. */
export function nextPlan(now: Date): Date {
  const at = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 5));
  if (at <= now) at.setUTCDate(at.getUTCDate() + 1);
  return at;
}

const hhmm = (at: Date) => at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

const POLL_MS = 10_000;
// Run now is asynchronous: keep polling until the run has taken its lease (Aurora may be waking).
const START_WINDOW_MS = 90_000;

export function autoIngestPollInterval(
  data: AutoIngestState | undefined,
  awaitingSince: number | null,
  now: number,
): number | false {
  if (data?.running) return POLL_MS;
  return awaitingSince !== null && now - awaitingSince < START_WINDOW_MS ? POLL_MS : false;
}

export function AutoIngestPanel({ styleNames }: { styleNames?: Map<number, string> }) {
  const { t } = useTranslation();
  const [awaitingSince, setAwaitingSince] = useState<number | null>(null);
  const query = useAutoIngest((data) => autoIngestPollInterval(data, awaitingSince, Date.now()));
  const save = useSaveAutoIngest();
  const run = useRunAutoIngest();
  const [form, setForm] = useState<Form | null>(null);

  // Re-init only when the saved settings change: polling refreshes last_run every 10 s, and
  // structural sharing keeps `settings` the same object while it is unchanged.
  const saved = query.data?.settings;
  useEffect(() => {
    if (!saved) return;
    const s = saved;
    setForm({
      enabled: s.enabled,
      mode: s.mode,
      times: s.fixed_times.join(', '),
      runsPerDay: s.runs_per_day,
      // Never saved: start from the admin's own timezone rather than the UTC default.
      timezone: s.updated_at ? s.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone,
      periodsPerRun: s.periods_per_run,
      floor: s.backfill_floor,
    });
  }, [saved]);

  const zones = useMemo(
    () =>
      Array.from(new Set(['UTC', form?.timezone ?? 'UTC', ...Intl.supportedValuesOf('timeZone')])),
    [form?.timezone],
  );

  if (query.isLoading || (query.data && !form)) return <Skeleton height={300} />;
  if (query.isError || !query.data || !form) {
    return <Alert color="red">{t('admin.auto_ingest.load_failed')}</Alert>;
  }

  const data = query.data;
  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });
  const styleName = (id: number) => styleNames?.get(id) ?? t('admin.auto_ingest.style', { id });

  const times = parseTimes(form.times);
  const timesOk = timesValid(times);
  const runsPerDay = intIn(form.runsPerDay, 1, 12);
  const periodsPerRun = intIn(form.periodsPerRun, 1, 10);
  const floorOk =
    /^\d{4}-\d{2}-\d{2}$/.test(form.floor) && form.floor >= '2000-01-01' && form.floor <= today();
  const valid =
    (form.mode === 'random' || timesOk) && runsPerDay !== null && periodsPerRun !== null && floorOk;

  const submit = async () => {
    if (!valid) return;
    const body: AutoIngestSettingsBody = {
      enabled: form.enabled,
      mode: form.mode,
      // Random mode keeps the saved times when the hidden field holds an unfinished edit.
      fixed_times: timesOk ? times : data.settings.fixed_times,
      runs_per_day: runsPerDay,
      timezone: form.timezone,
      periods_per_run: periodsPerRun,
      backfill_floor: form.floor,
    };
    try {
      await save.mutateAsync(body);
      notifications.show({ color: 'green', title: t('admin.auto_ingest.saved'), message: '' });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: t('admin.auto_ingest.save_failed'),
        message: err instanceof Error ? err.message : '',
      });
    }
  };

  const runNow = async () => {
    try {
      await run.mutateAsync();
      setAwaitingSince(Date.now());
      notifications.show({
        color: 'green',
        title: t('admin.auto_ingest.run_started'),
        message: '',
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: t('admin.auto_ingest.run_failed'),
        message: err instanceof Error ? err.message : '',
      });
    }
  };

  const a = (key: string, opts?: Record<string, unknown>) => t(`admin.auto_ingest.${key}`, opts);
  const pair = (p: { style_id: number; week_year: number; week_number: number }) =>
    `${styleName(p.style_id)} · ${week(p.week_year, p.week_number)}`;
  const last = data.last_run;
  const inProgress = !!last?.in_progress;
  const now = dayjs();
  const next = data.planned_runs.map((at) => dayjs(at)).find((at) => at.isAfter(now));
  const plan = data.settings.enabled && !next ? dayjs(nextPlan(now.toDate())) : null;
  const released = (last?.pairs ?? []).reduce(
    (sum, p) => sum + (p.ok ? (p.item_count ?? 0) : 0),
    0,
  );
  const [tone, status] = !last
    ? [null, null]
    : inProgress
      ? data.running
        ? ['green', a('running')]
        : ['red', a('interrupted')]
      : last.failed_step
        ? ['red', a('login_failed_badge')]
        : last.pairs.some((p) => !p.ok)
          ? ['orange', a('errors')]
          : ['gray', a('done')];

  return (
    <Stack gap="sm">
      <Group gap="xs" align="center">
        <Text fw={600}>{a('title')}</Text>
        <Tooltip
          label={a('hint')}
          multiline
          w={340}
          withArrow
          events={{ hover: true, focus: true, touch: true }}
        >
          <ActionIcon variant="subtle" color="gray" size="sm" aria-label={a('about')}>
            <IconInfoCircle size={16} />
          </ActionIcon>
        </Tooltip>
        <Text size="sm" c="dimmed">
          {a('due_week', { week: week(data.due_week.week_year, data.due_week.week_number) })}
        </Text>
      </Group>
      <SimpleGrid type="container" cols={{ base: 1, '560px': 2, '1100px': 4 }}>
        <StatCard
          title={a('schedule')}
          status={
            <Switch
              size="xs"
              labelPosition="left"
              label={a('enabled')}
              checked={form.enabled}
              onChange={(e) => set({ enabled: e.currentTarget.checked })}
            />
          }
        >
          <SegmentedControl
            size="xs"
            fullWidth
            value={form.mode}
            onChange={(v) => set({ mode: v as Form['mode'] })}
            data={[
              { value: 'fixed', label: a('mode_fixed') },
              { value: 'random', label: a('mode_random') },
            ]}
          />
          <SimpleGrid cols={2} spacing="xs" verticalSpacing="xs">
            {form.mode === 'fixed' ? (
              <TextInput
                size="xs"
                label={a('times')}
                placeholder="09:00, 15:00, 21:00"
                value={form.times}
                onChange={(e) => set({ times: e.currentTarget.value })}
                error={timesOk ? null : a('times_invalid')}
              />
            ) : (
              <NumberInput
                size="xs"
                label={a('runs_per_day')}
                min={1}
                max={12}
                allowDecimal={false}
                value={form.runsPerDay}
                onChange={(v) => set({ runsPerDay: v })}
              />
            )}
            <Select
              size="xs"
              label={a('timezone')}
              data={zones}
              searchable
              allowDeselect={false}
              value={form.timezone}
              onChange={(v) => v && set({ timezone: v })}
            />
            <NumberInput
              size="xs"
              label={a('periods_per_run')}
              min={1}
              max={10}
              allowDecimal={false}
              value={form.periodsPerRun}
              onChange={(v) => set({ periodsPerRun: v })}
            />
            <TextInput
              size="xs"
              type="date"
              label={a('floor')}
              min="2000-01-01"
              max={today()}
              value={form.floor}
              onChange={(e) => set({ floor: e.currentTarget.value })}
              error={floorOk ? null : a('floor_invalid')}
            />
          </SimpleGrid>
          <Group gap="xs">
            <Button size="xs" onClick={submit} loading={save.isPending} disabled={!valid}>
              {a('save')}
            </Button>
            <Button
              size="xs"
              variant="default"
              onClick={runNow}
              loading={run.isPending}
              disabled={data.running}
            >
              {a('run_now')}
            </Button>
          </Group>
        </StatCard>

        <StatCard
          title={a('planned')}
          status={
            <Badge color={data.settings.enabled ? 'green' : 'gray'} variant="light">
              {a(data.settings.enabled ? 'on' : 'off')}
            </Badge>
          }
          value={next ? hhmm(next.toDate()) : plan ? hhmm(plan.toDate()) : '—'}
          caption={
            next
              ? next.fromNow()
              : plan
                ? a('next_plan', { ago: plan.fromNow() })
                : a('none_planned')
          }
        >
          <Stack gap={2}>
            {data.planned_runs.map((at) => (
              <Row
                key={at}
                label={new Date(at).toLocaleString([], {
                  weekday: 'short',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
                value={dayjs(at).fromNow()}
                dimmed={!dayjs(at).isAfter(now)}
              />
            ))}
          </Stack>
        </StatCard>

        <StatCard
          title={a('last_run')}
          status={
            tone && (
              <Badge color={tone} variant="light">
                {status}
              </Badge>
            )
          }
          value={last ? fmt(released) : '—'}
          caption={
            last
              ? [a('releases'), dayjs(last.at).fromNow(), last.manual && a('manual')]
                  .filter(Boolean)
                  .join(' · ')
              : a('never_run')
          }
        >
          {last?.failed_step && (
            <Note c="red">
              {a('login_failed', { step: last.failed_step, status: last.status ?? '—' })}
            </Note>
          )}
          {last && last.pairs.length === 0 && !last.failed_step && !inProgress && (
            <Note>{a('nothing_due')}</Note>
          )}
          <Stack gap={2}>
            {last?.pairs.map((p) => (
              <Row
                key={`${p.style_id}-${p.week_year}-${p.week_number}`}
                label={pair(p)}
                value={p.ok ? fmt(p.item_count ?? 0) : (p.error ?? '')}
                error={!p.ok}
              />
            ))}
            {inProgress && data.running && (
              <Group gap={6} wrap="nowrap">
                <Loader size="xs" />
                <Text size="sm">
                  {last?.current
                    ? a('fetching', {
                        pair: pair(last.current),
                        n: (last.pairs?.length ?? 0) + 1,
                        total: last.total ?? '?',
                      })
                    : a('logging_in')}
                </Text>
              </Group>
            )}
          </Stack>
        </StatCard>

        <StatCard title={a('stuck')} value={fmt(data.stuck.length)} caption={a('stuck_caption')}>
          <Stack gap={2}>
            {data.stuck.map((p) => (
              <Row
                key={`${p.style_id}-${p.week_year}-${p.week_number}`}
                label={pair(p)}
                value={p.last_error ?? ''}
                error
              />
            ))}
          </Stack>
        </StatCard>
      </SimpleGrid>
    </Stack>
  );
}

/** A card row: what on the left, how it went on the right. The label wraps; a long error
 * truncates and keeps its full text in the title. */
function Row(props: { label: string; value: string; error?: boolean; dimmed?: boolean }) {
  const { label, value, error, dimmed } = props;
  const c = error ? 'red' : dimmed ? 'dimmed' : undefined;
  return (
    <Group justify="space-between" wrap="nowrap" gap="xs" data-row={label}>
      <Text size="sm" c={c} style={{ minWidth: 0 }}>
        {label}
      </Text>
      <Text
        size="sm"
        fw={600}
        c={c}
        truncate="end"
        title={value}
        maw="50%"
        style={{ flexShrink: 0 }}
      >
        {value}
      </Text>
    </Group>
  );
}
