import { Paper, Stack, Table, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { api } from '../../../api/client';
import type { components } from '../../../api/schema';
import { Ghost, GhostScope, useRemembered } from '../../../components/Ghost';

dayjs.extend(relativeTime);

type Analysis = components['schemas']['AnalysisStatus'];
type Item = Analysis['models']['items'][number];

// ponytail: the account caps Lambda memory at 3008 MB and the ML worker runs at it; update this
// (and the "/ 3.0 GB" copy) if the worker's memory changes.
const MEMORY_CAP_MB = 3008;
const MEMORY_WARN = 0.85;
const FIRST_MIN = 20; // taps before the first-button hit rate means anything
const DASH = '—';

const fmt = (n: number) => n.toLocaleString('en-US');

/** The table's ghost while the status loads: as many rows as last time. */
const ghostItem = (i: number): Item => ({
  user_id: `ghost-${i}`,
  user_name: 'Placeholder',
  style_id: `ghost-${i}`,
  style_name: 'Placeholder style name',
  version: 2,
  trained_at: '2026-10-27T00:00:00Z',
  retrain_pending: false,
  labels_since_training: 0,
  n_labels: 1_200,
  rows_total: 1_200,
  n_keep: 410,
  keep_auc: 0.842,
  category_bacc: 0.611,
  n_classes: 3,
  first_hit: 0.58,
  first_n: 64,
  predictions: 3_120,
  max_rss_mb: 1_400,
});

/** Admin table of the triage suggestion models: one row per (user, style) with a model row or a
 * live block. Reads the analysis status the pipeline block polls, so it adds no request. */
export function SuggestionModels() {
  const { t } = useTranslation();
  const k = (key: string, opts?: Record<string, unknown>) =>
    t(`admin.suggestion_models.${key}`, opts);
  const { data, isPending } = useQuery({
    queryKey: ['admin', 'analysisStatus'],
    queryFn: () => api<Analysis>('/admin/analysis/status'),
  });
  const rows = useRemembered('admin.suggestion_models', data?.models.items.length, 3);
  if (!data && !isPending) return null;
  const items = data?.models.items ?? Array.from({ length: rows }, (_, i) => ghostItem(i));

  const model = (m: Item) =>
    m.version > 0
      ? k('version', { version: m.version, ago: dayjs(m.trained_at).fromNow() })
      : m.retrain_pending
        ? k('queued')
        : k('waiting', { since: m.labels_since_training ?? 0 });

  const labels = (m: Item) => {
    if (m.version === 0 || m.n_labels === null) return DASH;
    const opts = { n: fmt(m.n_labels), keep: fmt(m.n_keep ?? 0) };
    return m.rows_total !== null && m.rows_total > m.n_labels
      ? k('labels_capped', { ...opts, total: fmt(m.rows_total) })
      : k('labels_value', opts);
  };

  const first = (m: Item) => {
    if (m.version === 0) return DASH;
    const n = m.first_n ?? 0; // a model with no taps scored yet reads as 0 of 20
    return n >= FIRST_MIN
      ? k('first_hit', { pct: Math.round((m.first_hit ?? 0) * 100), n: fmt(n) })
      : k('first_few', { n });
  };

  const memory = (mb: number | null) => {
    if (mb === null) return DASH;
    const warn = mb >= MEMORY_CAP_MB * MEMORY_WARN;
    return (
      <Text span inherit c={warn ? 'orange' : undefined} data-warn={warn || undefined}>
        {k('memory_value', { gb: (mb / 1024).toFixed(1) })}
      </Text>
    );
  };

  const table = (
    <Stack gap="sm">
      <Text fw={600}>{k('title')}</Text>
      {items.length === 0 ? (
        <Ghost>
          <Text size="sm" c="dimmed">
            {k('empty')}
          </Text>
        </Ghost>
      ) : (
        <Paper withBorder radius="md">
          <Table.ScrollContainer minWidth={900}>
            <Table fz="sm" highlightOnHover style={{ whiteSpace: 'nowrap' }}>
              <Table.Thead>
                <Table.Tr>
                  {[
                    'user',
                    'style',
                    'model',
                    'labels',
                    'keep_auc',
                    'categories',
                    'first_button',
                    'predictions',
                    'memory',
                  ].map((col) => (
                    <Table.Th key={col}>{k(col)}</Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.map((m) => (
                  <Table.Tr key={`${m.user_id}/${m.style_id}`}>
                    {[
                      m.user_name,
                      m.style_name,
                      model(m),
                      labels(m),
                      m.keep_auc === null ? DASH : m.keep_auc.toFixed(3),
                      m.category_bacc === null
                        ? DASH
                        : k('categories_value', {
                            bacc: m.category_bacc.toFixed(3),
                            n: m.n_classes ?? 0,
                          }),
                      first(m),
                      fmt(m.predictions),
                      memory(m.max_rss_mb),
                    ].map((cell, i) => (
                      <Table.Td key={i}>
                        <Ghost>{cell}</Ghost>
                      </Table.Td>
                    ))}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
    </Stack>
  );
  return <GhostScope on={!data}>{table}</GhostScope>;
}
