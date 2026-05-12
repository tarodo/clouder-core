import { Button, Group, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export interface PublishConfirmModalProps {
  opened: boolean;
  onClose: () => void;
  onConfirm: () => void;
  playlistName: string;
  trackCount: number;
  loading: boolean;
}

export function PublishConfirmModal({
  opened,
  onClose,
  onConfirm,
  playlistName,
  trackCount,
  loading,
}: PublishConfirmModalProps) {
  const { t } = useTranslation();
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('playlists.publish.confirm_title')}
      centered
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        <Text>
          {t('playlists.publish.confirm_body', { name: playlistName, count: trackCount })}
        </Text>
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={loading}>
            {t('playlists.publish.cancel')}
          </Button>
          <Button color="red" onClick={onConfirm} loading={loading}>
            {t('playlists.publish.confirm_cta')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
