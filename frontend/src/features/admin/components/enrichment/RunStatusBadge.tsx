import { Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';

const COLORS: Record<string, string> = {
  queued: 'gray', running: 'blue', completed: 'green', failed: 'red',
  none: 'gray', outdated: 'yellow',
};

export function RunStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const key = `admin_enrichment.status.${status}`;
  const label = t(key, { defaultValue: status });
  return <Badge color={COLORS[status] ?? 'gray'}>{label}</Badge>;
}
