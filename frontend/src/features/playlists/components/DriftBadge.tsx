import { Badge, Tooltip } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

export function DriftBadge() {
  const { t } = useTranslation();
  return (
    <Tooltip label={t('playlists.drift_badge.tooltip')} withinPortal>
      <Badge
        color="gray"
        variant="light"
        leftSection={<IconAlertTriangle size={12} />}
        size="sm"
        tt="none"
        fw={400}
      >
        {t('playlists.drift_badge.label')}
      </Badge>
    </Tooltip>
  );
}
