import { Badge, Tooltip } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

type DriftTarget = 'spotify' | 'ytmusic';

export function DriftBadge({ target = 'spotify' }: { target?: DriftTarget }) {
  const { t } = useTranslation();
  const keyBase = target === 'ytmusic' ? 'playlists.ytmusic_drift_badge' : 'playlists.drift_badge';
  return (
    <Tooltip label={t(`${keyBase}.tooltip`)} withinPortal>
      <Badge
        color="gray"
        variant="light"
        leftSection={<IconAlertTriangle size={12} />}
        size="sm"
        tt="none"
        fw={400}
      >
        {t(`${keyBase}.label`)}
      </Badge>
    </Tooltip>
  );
}
