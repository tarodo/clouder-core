import { useRef } from 'react';
import {
  ActionIcon,
  Avatar,
  Box,
  FileButton,
  LoadingOverlay,
  Stack,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { modals } from '@mantine/modals';
import { IconPhoto, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useUploadCover } from '../hooks/useUploadCover';
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
    // Stretches to the meta-panel row height (Group align="stretch") and renders
    // a square cover of that height, so the cover matches the content block.
    <Box style={{ alignSelf: 'stretch', display: 'flex' }}>
      <Box style={{ position: 'relative', height: '100%', aspectRatio: '1 / 1' }}>
        <FileButton accept="image/jpeg,image/png" onChange={handleFile} resetRef={resetRef}>
          {(props) => (
            <UnstyledButton
              {...props}
              aria-label={t('playlists.cover.replace')}
              style={{ display: 'block', width: '100%', height: '100%', borderRadius: 'var(--mantine-radius-md)' }}
            >
              <Avatar
                src={coverUrl}
                alt={t('playlists.cover.placeholder_alt')}
                radius="md"
                color="gray"
                style={{ width: '100%', height: '100%', cursor: 'pointer' }}
              >
                <Stack gap={4} align="center" justify="center" px="xs">
                  <IconPhoto size={36} />
                  <Text size="xs" c="dimmed" ta="center">
                    {t('playlists.cover.help_text')}
                  </Text>
                  <Text size="xs" c="dimmed" ta="center">
                    {t('playlists.cover.upload_hint')}
                  </Text>
                </Stack>
              </Avatar>
            </UnstyledButton>
          )}
        </FileButton>
        {coverUrl ? (
          <ActionIcon
            variant="filled"
            color="dark"
            size="sm"
            onClick={handleRemove}
            loading={clear.isPending}
            aria-label={t('playlists.cover.remove')}
            style={{ position: 'absolute', top: 6, right: 6 }}
          >
            <IconTrash size={14} />
          </ActionIcon>
        ) : null}
        <LoadingOverlay visible={upload.isPending} overlayProps={{ radius: 'md' }} />
      </Box>
    </Box>
  );
}
