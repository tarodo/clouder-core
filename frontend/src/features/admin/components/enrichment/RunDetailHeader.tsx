import { Stack, Group, Title, Anchor, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { RunDetail } from '../../../../api/labels';
import { RunStatusBadge } from './RunStatusBadge';
import { Ghost } from '../../../../components/Ghost';

export function RunDetailHeader({ run }: { run: RunDetail }) {
  const { t } = useTranslation();
  return (
    <Stack gap="xs">
      <Anchor component={Link} to="/admin/labels/enrich/runs" size="sm">
        ← {t('admin_enrichment.run_detail.back_to_runs')}
      </Anchor>
      <Group gap="md" align="center">
        <Ghost>
          <Title order={2}>Run {run.id.slice(0, 8)}…</Title>
        </Ghost>
        <Ghost>
          <RunStatusBadge status={run.status} />
        </Ghost>
      </Group>
      <Group gap="md">
        <Ghost>
          <Text size="sm">
            {t('admin_enrichment.run_detail.counters_total')}: {run.cells_total}{' '}
            · {t('admin_enrichment.run_detail.counters_ok')}: {run.cells_ok}{' '}
            · {t('admin_enrichment.run_detail.counters_err')}: {run.cells_error}
          </Text>
        </Ghost>
        {typeof run.cost_usd === 'number' && (
          <Ghost>
            <Text size="sm">Cost: ${run.cost_usd.toFixed(4)}</Text>
          </Ghost>
        )}
      </Group>
      <Ghost>
        <Text size="sm" c="dimmed">
          {run.prompt_slug}@{run.prompt_version} · vendors: {(run.vendors ?? []).join(', ')}
        </Text>
      </Ghost>
    </Stack>
  );
}
