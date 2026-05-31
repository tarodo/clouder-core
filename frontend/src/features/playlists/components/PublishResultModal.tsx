import { Anchor, Button, Group, List, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export interface PublishResultModalProps {
  opened: boolean;
  onClose: () => void;
  skippedTracks: { track_id: string; title: string; reason: string }[] | null;
  openUrl: string;
  openLabelKey: string; // i18n key, e.g. 'playlists.publish.open_in_spotify'
}

export function PublishResultModal({
  opened, onClose, skippedTracks, openUrl, openLabelKey,
}: PublishResultModalProps) {
  const { t } = useTranslation();
  if (!skippedTracks) return null;
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('playlists.publish.result_skipped_title', { count: skippedTracks.length })}
      centered
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        <Text>{t('playlists.publish.result_skipped_body')}</Text>
        <List size="sm">
          {skippedTracks.map((s) => (
            <List.Item key={s.track_id}>
              {s.title} — {s.reason}
            </List.Item>
          ))}
        </List>
        <Group justify="space-between">
          <Anchor href={openUrl} target="_blank" rel="noopener noreferrer">
            {t(openLabelKey)}
          </Anchor>
          <Button onClick={onClose}>{t('playlists.form.cancel')}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
