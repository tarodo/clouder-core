import { Anchor, Button, Group, List, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { PublishResult } from '../lib/playlistTypes';

export interface PublishResultModalProps {
  opened: boolean;
  onClose: () => void;
  result: PublishResult | null;
}

export function PublishResultModal({ opened, onClose, result }: PublishResultModalProps) {
  const { t } = useTranslation();
  if (!result) return null;
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('playlists.publish.result_skipped_title', { count: result.skipped_tracks.length })}
      centered
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        <Text>{t('playlists.publish.result_skipped_body')}</Text>
        <List size="sm">
          {result.skipped_tracks.map((s) => (
            <List.Item key={s.track_id}>
              {s.title} — {s.reason}
            </List.Item>
          ))}
        </List>
        <Group justify="space-between">
          <Anchor href={result.spotify_url} target="_blank" rel="noopener noreferrer">
            {t('playlists.publish.open_in_spotify')}
          </Anchor>
          <Button onClick={onClose}>{t('playlists.form.cancel')}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
