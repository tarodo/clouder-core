import {
  Alert,
  Button,
  Collapse,
  Group,
  NumberInput,
  Stack,
  Switch,
  Text,
} from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { saturdayWeekRange } from '../lib/saturdayWeek';
import { useBpToken } from '../lib/bpTokenStore';
import { useStartIngest } from '../hooks/useStartIngest';
import { BpTokenInput } from './BpTokenInput';

interface Props {
  styleId: number;
  styleName: string;
  weekYear: number;
  weekNumber: number;
  onStarted: (run_id: string) => void;
}

function fmt(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function IngestForm({ styleId, weekYear, weekNumber, onStarted }: Props) {
  const { t } = useTranslation();
  const [override, setOverride] = useState(false);
  const [stdStart, stdEnd] = saturdayWeekRange(weekYear, weekNumber);
  const [start, setStart] = useState(fmt(stdStart));
  const [end, setEnd] = useState(fmt(stdEnd));
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [labelCount, setLabelCount] = useState<number | ''>('');
  const token = useBpToken();
  const mutation = useStartIngest();

  const submit = () => {
    if (!token) return;
    const payload = {
      style_id: styleId,
      week_year: weekYear,
      week_number: weekNumber,
      bp_token: token,
      ...(override ? { period_start: start, period_end: end } : {}),
      ...(typeof labelCount === 'number' ? { search_label_count: labelCount } : {}),
    };
    mutation.mutate(payload, {
      onSuccess: (data) => onStarted(data.run_id),
    });
  };

  return (
    <Stack gap="sm">
      <BpTokenInput />
      <Switch
        label={t('admin.ingest.override')}
        checked={override}
        onChange={(e) => setOverride(e.currentTarget.checked)}
      />
      <Collapse expanded={override}>
        <Stack gap={4}>
          <Text size="xs" c="dimmed">
            {t('admin.ingest.standard_week', { start: fmt(stdStart), end: fmt(stdEnd) })}
          </Text>
          <Group grow>
            <input
              type="date"
              aria-label="period_start"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
            <input
              type="date"
              aria-label="period_end"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </Group>
        </Stack>
      </Collapse>
      <Stack gap={2}>
        <Switch
          size="xs"
          label={t('admin.ingest.advanced')}
          checked={advancedOpen}
          onChange={(e) => setAdvancedOpen(e.currentTarget.checked)}
        />
        <Collapse expanded={advancedOpen}>
          <NumberInput
            label={t('admin.ingest.search_label_count')}
            min={1}
            max={200}
            value={labelCount}
            onChange={(v) => setLabelCount(typeof v === 'number' ? v : '')}
          />
        </Collapse>
      </Stack>
      {mutation.isError && (
        <Alert color="red" title={t('admin.ingest.failed_title')}>
          {(mutation.error as Error)?.message ?? t('admin.ingest.unknown_error')}
        </Alert>
      )}
      <Button onClick={submit} loading={mutation.isPending} disabled={!token}>
        {t('admin.ingest.start')}
      </Button>
    </Stack>
  );
}
