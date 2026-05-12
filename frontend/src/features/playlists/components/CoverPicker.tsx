import { useRef } from 'react';
import { Avatar, Button, FileButton, Group, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { modals } from '@mantine/modals';
import { IconPhoto, IconUpload, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useUploadCover, MAX_COVER_BYTES } from '../hooks/useUploadCover';
import { useClearCover } from '../hooks/useClearCover';

export interface CoverPickerProps {
  playlistId: string;
  coverUrl: string | null;
}

export function CoverPicker({ playlistId, coverUrl }: CoverPickerProps) {
  const { t } = useTranslation();
  const upload = useUploadCover();
  const clear = useClearCover();
  const resetRef = useRef<() => void>(null);

  async function handleFile(file: File | null) {
    if (!file) return;
    try {
      await upload.mutateAsync({ playlistId, file });
      notifications.show({ message: t('playlists.toast.cover_saved'), color: 'green' });
    } catch (err) {
      const msg = err instanceof Error ? err.message : '';
      if (msg === 'cover_too_large' || msg.includes('cover_too_large')) {
        notifications.show({ message: t('playlists.toast.cover_too_large'), color: 'red' });
      } else if (msg === 'unsupported_content_type') {
        notifications.show({ message: t('playlists.toast.cover_unsupported'), color: 'red' });
      } else {
        notifications.show({ message: t('playlists.toast.cover_failed'), color: 'red' });
      }
    } finally {
      resetRef.current?.();
    }
  }

  function handleRemove() {
    modals.openConfirmModal({
      title: t('playlists.cover.remove'),
      labels: {
        confirm: t('playlists.cover.remove'),
        cancel: t('playlists.form.cancel'),
      },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await clear.mutateAsync(playlistId);
          notifications.show({ message: t('playlists.toast.cover_removed'), color: 'green' });
        } catch {
          notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  return (
    <Stack gap="xs" align="center">
      <Avatar
        src={coverUrl}
        alt={t('playlists.cover.placeholder_alt')}
        size={160}
        radius="md"
        color="gray"
      >
        <IconPhoto size={48} />
      </Avatar>
      <Group gap="xs" wrap="nowrap">
        <FileButton
          accept="image/jpeg,image/png"
          onChange={handleFile}
          resetRef={resetRef}
        >
          {(props) => (
            <Button
              {...props}
              leftSection={<IconUpload size={14} />}
              variant="default"
              size="xs"
              loading={upload.isPending}
            >
              {t('playlists.cover.replace')}
            </Button>
          )}
        </FileButton>
        {coverUrl ? (
          <Button
            leftSection={<IconTrash size={14} />}
            variant="default"
            color="red"
            size="xs"
            onClick={handleRemove}
            loading={clear.isPending}
          >
            {t('playlists.cover.remove')}
          </Button>
        ) : null}
      </Group>
      <Text size="xs" c="dimmed">
        {t('playlists.cover.help_text')} ({Math.floor(MAX_COVER_BYTES / 1024)} KB)
      </Text>
    </Stack>
  );
}
