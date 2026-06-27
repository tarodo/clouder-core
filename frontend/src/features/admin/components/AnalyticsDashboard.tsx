import { Alert, Card, Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { BarChart, LineChart } from '@mantine/charts';
import { useTranslation } from 'react-i18next';
import { useAnalytics, type AnalyticsRange } from '../hooks/useAnalytics';
import type { DashboardSpec, PanelSpec } from '../lib/dashboards';

const COLORS = ['indigo.6', 'teal.6', 'grape.6'];

type Row = Record<string, unknown>;
type Freshness = { newest_dt?: string | null; lag_hours?: number | null };

function PanelView({ panel, data }: { panel: PanelSpec; data: Record<string, unknown> | undefined }) {
  const { t } = useTranslation();
  const rows = (data?.[panel.dataKey] as Row[] | undefined) ?? [];
  const cols = rows.length > 0 ? Object.keys(rows[0]!) : [];
  const series = panel.series.map((s, i) => ({
    name: s.key,
    label: t(s.labelKey),
    color: COLORS[i % COLORS.length],
  }));

  if (rows.length === 0) {
    return (
      <Stack gap="xs" data-testid={`panel-${panel.dataKey}`}>
        <Text fw={600} size="sm">{t(panel.titleKey)}</Text>
        <Text c="dimmed" size="sm">{t('admin.analytics.empty')}</Text>
      </Stack>
    );
  }

  return (
    <Stack gap="xs" data-testid={`panel-${panel.dataKey}`}>
      <Text fw={600} size="sm">{t(panel.titleKey)}</Text>
      {panel.chart === 'line' ? (
        <LineChart h={200} data={rows} dataKey={panel.xKey} series={series} withLegend />
      ) : (
        <BarChart h={200} data={rows} dataKey={panel.xKey} series={series} withLegend />
      )}
      <Table striped withTableBorder>
        <Table.Thead>
          <Table.Tr>{cols.map((c) => (<Table.Th key={c}>{c}</Table.Th>))}</Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r, i) => (
            <Table.Tr key={i}>
              {cols.map((c) => (<Table.Td key={c}>{String(r[c] ?? '')}</Table.Td>))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

export function AnalyticsDashboard({
  spec,
  range,
}: {
  spec: DashboardSpec;
  range: AnalyticsRange;
}) {
  const { t } = useTranslation();
  const q = useAnalytics(spec.name, range);
  const data = q.data as Record<string, unknown> | undefined;
  const freshness = data?.freshness as Freshness | undefined;

  return (
    <Card withBorder padding="md" data-testid={`dashboard-${spec.name}`}>
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>{t(spec.titleKey)}</Title>
          {spec.showFreshness && freshness && (
            <Text
              size="sm"
              c={typeof freshness.lag_hours === 'number' && freshness.lag_hours > 36 ? 'red' : 'dimmed'}
            >
              {t('admin.analytics.ops.freshness', {
                dt: freshness.newest_dt ?? '—',
                lag: freshness.lag_hours ?? '—',
              })}
            </Text>
          )}
        </Group>

        {q.isLoading && <Loader size="sm" />}
        {q.isError && <Alert color="red">{t('admin.analytics.load_failed')}</Alert>}
        {!q.isLoading && !q.isError &&
          spec.panels.map((panel) => (
            <PanelView key={panel.dataKey} panel={panel} data={data} />
          ))}
      </Stack>
    </Card>
  );
}
