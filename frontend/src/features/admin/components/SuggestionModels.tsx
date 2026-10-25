import { Paper, Stack, Table, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { api } from '../../../api/client';
import type { components } from '../../../api/schema';

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

/** Admin table of the triage suggestion models: one row per (user, style) with a model row or a
 * live block. Reads the analysis status the pipeline block polls, so it adds no request. */
export function SuggestionModels() {
  const { t } = useTranslation();
  const k = (key: string, opts?: Record<string, unknown>) =>
    t(`admin.suggestion_models.${key}`, opts);
  const { data } = useQuery({
    queryKey: ['admin', 'analysisStatus'],
    queryFn: () => api<Analysis>('/admin/analysis/status'),
  });
  if (!data) return null;
  const items = data.models.items;

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
    const n = m.first_n ?? 0; // no taps scored yet reads as 0 of 20
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

  return (
    <Stack gap="sm">
      <Text fw={600}>{k('title')}</Text>
      {items.length === 0 ? (
        <Text size="sm" c="dimmed">
          {k('empty')}
        </Text>
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
                    <Table.Td>{m.user_name}</Table.Td>
                    <Table.Td>{m.style_name}</Table.Td>
                    <Table.Td>{model(m)}</Table.Td>
                    <Table.Td>{labels(m)}</Table.Td>
                    <Table.Td>{m.keep_auc === null ? DASH : m.keep_auc.toFixed(3)}</Table.Td>
                    <Table.Td>
                      {m.category_bacc === null
                        ? DASH
                        : k('categories_value', {
                            bacc: m.category_bacc.toFixed(3),
                            n: m.n_classes ?? 0,
                          })}
                    </Table.Td>
                    <Table.Td>{first(m)}</Table.Td>
                    <Table.Td>{fmt(m.predictions)}</Table.Td>
                    <Table.Td>{memory(m.max_rss_mb)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
    </Stack>
  );
}
