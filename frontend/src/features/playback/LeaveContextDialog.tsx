import { Modal, Button, Group, Stack, Text } from '@mantine/core';
import { useBlocker } from 'react-router';
import { useTranslation } from 'react-i18next';
import { contextDifferent } from './routeContext';

export interface LeaveContextDialogProps {
  active: boolean;
  currentPath: string;
  onConfirm: () => void;
}

export function LeaveContextDialog({
  active,
  currentPath,
  onConfirm,
}: LeaveContextDialogProps) {
  const { t } = useTranslation();
  const blocker = useBlocker(({ nextLocation }) => {
    if (!active) return false;
    return contextDifferent(currentPath, nextLocation.pathname);
  });

  const open = blocker.state === 'blocked';

  return (
    <Modal
      opened={open}
      onClose={() => blocker.reset?.()}
      title={t('playback.leave_context.title')}
      centered
    >
      <Stack>
        <Text>{t('playback.leave_context.body')}</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => blocker.reset?.()}>
            {t('playback.leave_context.cancel')}
          </Button>
          <Button
            color="red"
            onClick={() => {
              onConfirm();
              blocker.proceed?.();
            }}
          >
            {t('playback.leave_context.confirm')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
