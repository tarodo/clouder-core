import { Drawer } from '@mantine/core';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export interface DeviceDrawerProps {
  opened: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function DeviceDrawer({ opened, onClose, children }: DeviceDrawerProps) {
  const { t } = useTranslation();
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="bottom"
      title={t('playback.devices.title')}
      size="auto"
      lockScroll
    >
      {children}
    </Drawer>
  );
}
