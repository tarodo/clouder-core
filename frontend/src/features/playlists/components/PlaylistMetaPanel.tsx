import { useState } from 'react';
import {
  ActionIcon,
  Group,
  Stack,
  Switch,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from '@mantine/core';
import { IconCheck, IconPencil, IconX } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import type { Playlist } from '../lib/playlistTypes';
import { playlistNameSchema, playlistDescriptionSchema } from '../lib/playlistSchemas';
import { translateFieldError } from '../lib/errorMessages';
import { CoverPicker } from './CoverPicker';

export interface PlaylistMetaPanelProps {
  playlist: Playlist;
  onPatch: (input: { name?: string; description?: string | null; is_public?: boolean }) => Promise<void>;
  publishSlot?: React.ReactNode;
}

export function PlaylistMetaPanel({
  playlist,
  onPatch,
  publishSlot,
}: PlaylistMetaPanelProps) {
  const { t } = useTranslation();
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(playlist.name);
  const [nameError, setNameError] = useState<string | undefined>();
  const [editingDescription, setEditingDescription] = useState(false);
  const [descDraft, setDescDraft] = useState(playlist.description ?? '');
  const [descError, setDescError] = useState<string | undefined>();

  async function commitName() {
    const parsed = playlistNameSchema.safeParse(nameDraft);
    if (!parsed.success) {
      const code = parsed.error.issues[0]?.message;
      setNameError(translateFieldError(code, t) ?? t('playlists.errors.name_too_long'));
      return;
    }
    setNameError(undefined);
    setEditingName(false);
    try {
      await onPatch({ name: parsed.data });
    } catch {
      setNameDraft(playlist.name);
    }
  }
  function cancelName() {
    setNameDraft(playlist.name);
    setNameError(undefined);
    setEditingName(false);
  }

  async function commitDescription() {
    const value = descDraft.trim() === '' ? null : descDraft.trim();
    const parsed = playlistDescriptionSchema.safeParse(value);
    if (!parsed.success) {
      const code = parsed.error.issues[0]?.message;
      setDescError(translateFieldError(code, t) ?? t('playlists.errors.description_too_long'));
      return;
    }
    setDescError(undefined);
    setEditingDescription(false);
    try {
      await onPatch({ description: parsed.data });
    } catch {
      setDescDraft(playlist.description ?? '');
    }
  }
  function cancelDescription() {
    setDescDraft(playlist.description ?? '');
    setDescError(undefined);
    setEditingDescription(false);
  }

  async function togglePublic(checked: boolean) {
    try {
      await onPatch({ is_public: checked });
      notifications.show({ message: t('playlists.toast.visibility_saved'), color: 'green' });
    } catch {
      notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
    }
  }

  return (
    <Group align="flex-start" gap="lg" wrap="nowrap">
      <CoverPicker playlistId={playlist.id} coverUrl={playlist.cover_url} />
      <Stack gap="sm" flex={1}>
        {editingName ? (
          <Group gap="xs" wrap="nowrap">
            <TextInput
              value={nameDraft}
              onChange={(e) => setNameDraft(e.currentTarget.value)}
              maxLength={100}
              error={nameError}
              // eslint-disable-next-line jsx-a11y/no-autofocus
              autoFocus
              flex={1}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void commitName();
                if (e.key === 'Escape') cancelName();
              }}
            />
            <ActionIcon variant="subtle" onClick={() => void commitName()} aria-label="Save name">
              <IconCheck size={18} />
            </ActionIcon>
            <ActionIcon variant="subtle" onClick={cancelName} aria-label="Cancel">
              <IconX size={18} />
            </ActionIcon>
          </Group>
        ) : (
          <Group gap="xs" wrap="nowrap">
            <Title order={1}>{playlist.name}</Title>
            <Tooltip label={t('playlists.form.rename_title')} withinPortal>
              <ActionIcon
                variant="subtle"
                onClick={() => setEditingName(true)}
                aria-label={t('playlists.form.rename_title')}
              >
                <IconPencil size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        )}

        {editingDescription ? (
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Textarea
              value={descDraft}
              onChange={(e) => setDescDraft(e.currentTarget.value)}
              maxLength={300}
              autosize
              minRows={2}
              maxRows={6}
              error={descError}
              // eslint-disable-next-line jsx-a11y/no-autofocus
              autoFocus
              flex={1}
            />
            <ActionIcon variant="subtle" onClick={() => void commitDescription()} aria-label="Save description">
              <IconCheck size={18} />
            </ActionIcon>
            <ActionIcon variant="subtle" onClick={cancelDescription} aria-label="Cancel">
              <IconX size={18} />
            </ActionIcon>
          </Group>
        ) : (
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Text c="dimmed" style={{ minHeight: 24 }} flex={1}>
              {playlist.description ?? '—'}
            </Text>
            <Tooltip label={t('playlists.form.edit_description_title')} withinPortal>
              <ActionIcon
                variant="subtle"
                onClick={() => setEditingDescription(true)}
                aria-label={t('playlists.form.edit_description_title')}
              >
                <IconPencil size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        )}

        <Switch
          label={t('playlists.form.is_public_label')}
          checked={playlist.is_public}
          onChange={(e) => void togglePublic(e.currentTarget.checked)}
        />

        <Text c="dimmed" size="sm">
          {t('playlists.detail.stats', {
            count: playlist.track_count,
            when: playlist.updated_at.slice(0, 10),
          })}
        </Text>

        {publishSlot ? <div>{publishSlot}</div> : null}
      </Stack>
    </Group>
  );
}
