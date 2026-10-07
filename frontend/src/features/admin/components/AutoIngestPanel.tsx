import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Group,
  List,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import type { AutoIngestSettingsBody } from '../../../api/autoIngest';
import { useAutoIngest } from '../hooks/useAutoIngest';
import { useSaveAutoIngest } from '../hooks/useSaveAutoIngest';
import { useRunAutoIngest } from '../hooks/useRunAutoIngest';

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
  return raw.split(',').map((s) => s.trim()).filter(Boolean);
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

export function AutoIngestPanel({ styleNames }: { styleNames?: Map<number, string> }) {
  const { t } = useTranslation();
  const query = useAutoIngest();
  const save = useSaveAutoIngest();
  const run = useRunAutoIngest();
  const [form, setForm] = useState<Form | null>(null);

  useEffect(() => {
    if (!query.data) return;
    const s = query.data.settings;
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
  }, [query.data]);

  const zones = useMemo(
    () => Array.from(new Set(['UTC', form?.timezone ?? 'UTC', ...Intl.supportedValuesOf('timeZone')])),
    [form?.timezone],
  );

  if (query.isLoading || (query.data && !form)) return <Skeleton height={320} />;
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
  const floorOk = /^\d{4}-\d{2}-\d{2}$/.test(form.floor) && form.floor >= '2000-01-01' && form.floor <= today();
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
      notifications.show({ color: 'green', title: t('admin.auto_ingest.run_started'), message: '' });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: t('admin.auto_ingest.run_failed'),
        message: err instanceof Error ? err.message : '',
      });
    }
  };

  const last = data.last_run;

  return (
    <Card withBorder>
      <Stack gap="md">
        <Group justify="space-between">
          <Title order={4}>{t('admin.auto_ingest.title')}</Title>
          <Text size="sm" c="dimmed">
            {t('admin.auto_ingest.due_week', {
              week: week(data.due_week.week_year, data.due_week.week_number),
            })}
          </Text>
        </Group>
        <Text size="sm" c="dimmed">{t('admin.auto_ingest.hint')}</Text>

        <Switch
          label={t('admin.auto_ingest.enabled')}
          checked={form.enabled}
          onChange={(e) => set({ enabled: e.currentTarget.checked })}
        />
        <SegmentedControl
          value={form.mode}
          onChange={(v) => set({ mode: v as Form['mode'] })}
          data={[
            { value: 'fixed', label: t('admin.auto_ingest.mode_fixed') },
            { value: 'random', label: t('admin.auto_ingest.mode_random') },
          ]}
        />
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          {form.mode === 'fixed' ? (
            <TextInput
              label={t('admin.auto_ingest.times')}
              description={t('admin.auto_ingest.times_hint')}
              value={form.times}
              onChange={(e) => set({ times: e.currentTarget.value })}
              error={timesOk ? null : t('admin.auto_ingest.times_invalid')}
            />
          ) : (
            <NumberInput
              label={t('admin.auto_ingest.runs_per_day')}
              description={t('admin.auto_ingest.runs_per_day_hint')}
              min={1}
              max={12}
              allowDecimal={false}
              value={form.runsPerDay}
              onChange={(v) => set({ runsPerDay: v })}
            />
          )}
          <Select
            label={t('admin.auto_ingest.timezone')}
            data={zones}
            searchable
            allowDeselect={false}
            value={form.timezone}
            onChange={(v) => v && set({ timezone: v })}
          />
          <NumberInput
            label={t('admin.auto_ingest.periods_per_run')}
            min={1}
            max={10}
            allowDecimal={false}
            value={form.periodsPerRun}
            onChange={(v) => set({ periodsPerRun: v })}
          />
          <TextInput
            type="date"
            label={t('admin.auto_ingest.floor')}
            description={t('admin.auto_ingest.floor_hint')}
            min="2000-01-01"
            max={today()}
            value={form.floor}
            onChange={(e) => set({ floor: e.currentTarget.value })}
            error={floorOk ? null : t('admin.auto_ingest.floor_invalid')}
          />
        </SimpleGrid>
        <Group>
          <Button onClick={submit} loading={save.isPending} disabled={!valid}>
            {t('admin.auto_ingest.save')}
          </Button>
          <Button variant="default" onClick={runNow} loading={run.isPending}>
            {t('admin.auto_ingest.run_now')}
          </Button>
        </Group>

        <SimpleGrid cols={{ base: 1, md: 3 }}>
          <Stack gap={4}>
            <Text fw={600} size="sm">{t('admin.auto_ingest.planned')}</Text>
            {data.planned_runs.length === 0 ? (
              <Text size="sm" c="dimmed">{t('admin.auto_ingest.none_planned')}</Text>
            ) : (
              <List size="sm">
                {data.planned_runs.map((at) => (
                  <List.Item key={at}>{new Date(at).toLocaleString()}</List.Item>
                ))}
              </List>
            )}
          </Stack>
          <Stack gap={4}>
            <Text fw={600} size="sm">{t('admin.auto_ingest.last_run')}</Text>
            {!last ? (
              <Text size="sm" c="dimmed">{t('admin.auto_ingest.never_run')}</Text>
            ) : (
              <>
                <Text size="sm">
                  {new Date(last.at).toLocaleString()}
                  {last.manual ? ` · ${t('admin.auto_ingest.manual')}` : ''}
                </Text>
                {last.failed_step && (
                  <Text size="sm" c="red">
                    {t('admin.auto_ingest.login_failed', {
                      step: last.failed_step,
                      status: last.status ?? '—',
                    })}
                  </Text>
                )}
                {last.pairs.length === 0 && !last.failed_step && (
                  <Text size="sm" c="dimmed">{t('admin.auto_ingest.nothing_due')}</Text>
                )}
                <List size="sm">
                  {last.pairs.map((p) => (
                    <List.Item key={`${p.style_id}-${p.week_year}-${p.week_number}`}>
                      <Text size="sm" c={p.ok ? undefined : 'red'}>
                        {styleName(p.style_id)} · {week(p.week_year, p.week_number)} —{' '}
                        {p.ok
                          ? t('admin.auto_ingest.releases', { count: p.item_count ?? 0 })
                          : p.error}
                      </Text>
                    </List.Item>
                  ))}
                </List>
              </>
            )}
          </Stack>
          <Stack gap={4}>
            <Text fw={600} size="sm">{t('admin.auto_ingest.stuck')}</Text>
            {data.stuck.length === 0 ? (
              <Text size="sm" c="dimmed">{t('admin.auto_ingest.none_stuck')}</Text>
            ) : (
              <List size="sm">
                {data.stuck.map((p) => (
                  <List.Item key={`${p.style_id}-${p.week_year}-${p.week_number}`}>
                    {styleName(p.style_id)} · {week(p.week_year, p.week_number)} — {p.last_error}
                  </List.Item>
                ))}
              </List>
            )}
          </Stack>
        </SimpleGrid>
      </Stack>
    </Card>
  );
}
