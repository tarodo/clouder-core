import { Badge, Tooltip } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

export function DriftBadge() {
  const { t } = useTranslation();
  return (
    <Tooltip label={t('playlists.drift_badge.tooltip')} withinPortal>
      <Badge color="yellow" leftSection={<IconAlertTriangle size={12} />} size="sm">
        {t('playlists.drift_badge.label')}
      </Badge>
    </Tooltip>
  );
}
