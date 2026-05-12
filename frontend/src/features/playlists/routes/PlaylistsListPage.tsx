import { useState } from 'react';
import { Button, Group, Stack, TextInput, Title } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useDebouncedValue } from '@mantine/hooks';
import { IconPlus, IconSearch } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { usePlaylists } from '../hooks/usePlaylists';
import { useCreatePlaylist } from '../hooks/useCreatePlaylist';
import { usePatchPlaylist } from '../hooks/usePatchPlaylist';
import { useDeletePlaylist } from '../hooks/useDeletePlaylist';
import { PlaylistsTable } from '../components/PlaylistsTable';
import { PlaylistFormDialog } from '../components/PlaylistFormDialog';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import type { Playlist } from '../lib/playlistTypes';

export function PlaylistsListPage() {
  const { t } = useTranslation();
  const [rawSearch, setRawSearch] = useState('');
  const [search] = useDebouncedValue(rawSearch.trim(), 300);
  const { data, isLoading, isError } = usePlaylists({ search });
  const create = useCreatePlaylist();
  const deleteMut = useDeletePlaylist();

  const [createOpen, setCreateOpen] = useState(false);
  const [createServerError, setCreateServerError] = useState<string | undefined>();
  const [renameTarget, setRenameTarget] = useState<Playlist | null>(null);
  const [descTarget, setDescTarget] = useState<Playlist | null>(null);
  const [renameServerError, setRenameServerError] = useState<string | undefined>();

  const renameMut = usePatchPlaylist(renameTarget?.id ?? '');
  const descMut = usePatchPlaylist(descTarget?.id ?? '');

  async function handleCreate(input: {
    name?: string;
    description?: string | null;
    is_public?: boolean;
  }) {
    setCreateServerError(undefined);
    try {
      await create.mutateAsync({
        name: input.name!,
        description: input.description ?? null,
        is_public: input.is_public ?? false,
      });
      notifications.show({ message: t('playlists.toast.created'), color: 'green' });
      setCreateOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setCreateServerError(t('playlists.errors.name_conflict'));
      } else if (err instanceof ApiError && err.status === 429) {
        notifications.show({ message: t('playlists.errors.limit_reached'), color: 'red' });
      } else {
        notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
      }
    }
  }

  async function handleRename(input: { name?: string }) {
    if (!renameTarget) return;
    setRenameServerError(undefined);
    try {
      await renameMut.mutateAsync({ name: input.name });
      notifications.show({ message: t('playlists.toast.renamed'), color: 'green' });
      setRenameTarget(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRenameServerError(t('playlists.errors.name_conflict'));
      } else {
        notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
      }
    }
  }

  async function handleEditDescription(input: { description?: string | null }) {
    if (!descTarget) return;
    try {
      await descMut.mutateAsync({ description: input.description ?? null });
      notifications.show({ message: t('playlists.toast.description_saved'), color: 'green' });
      setDescTarget(null);
    } catch {
      notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
    }
  }

  function openDelete(p: Playlist) {
    modals.openConfirmModal({
      title: t('playlists.detail.delete_cta'),
      children: p.name,
      labels: { confirm: t('playlists.detail.delete_cta'), cancel: t('playlists.form.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync(p.id);
          notifications.show({ message: t('playlists.toast.deleted'), color: 'green' });
        } catch {
          notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }
  const items = data?.items ?? [];

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center">
        <Title order={1}>{t('playlists.page_title')}</Title>
        <Group gap="sm">
          <TextInput
            placeholder={t('playlists.search_placeholder')}
            leftSection={<IconSearch size={16} />}
            value={rawSearch}
            onChange={(e) => setRawSearch(e.currentTarget.value)}
          />
          <Button leftSection={<IconPlus size={16} />} onClick={() => setCreateOpen(true)}>
            {t('playlists.create_cta')}
          </Button>
        </Group>
      </Group>

      {items.length === 0 ? (
        <EmptyState
          title={t('playlists.empty.title')}
          body={t('playlists.empty.body')}
        />
      ) : (
        <PlaylistsTable
          playlists={items}
          onRename={(p) => setRenameTarget(p)}
          onEditDescription={(p) => setDescTarget(p)}
          onDelete={openDelete}
        />
      )}

      <PlaylistFormDialog
        mode="create"
        opened={createOpen}
        initial={{ name: '', description: null, is_public: false }}
        submitting={create.isPending}
        onClose={() => {
          setCreateOpen(false);
          setCreateServerError(undefined);
        }}
        onSubmit={handleCreate}
        serverNameError={createServerError}
      />
      <PlaylistFormDialog
        mode="rename"
        opened={!!renameTarget}
        initial={
          renameTarget
            ? { name: renameTarget.name, description: renameTarget.description, is_public: renameTarget.is_public }
            : { name: '', description: null, is_public: false }
        }
        submitting={renameMut.isPending}
        onClose={() => {
          setRenameTarget(null);
          setRenameServerError(undefined);
        }}
        onSubmit={handleRename}
        serverNameError={renameServerError}
      />
      <PlaylistFormDialog
        mode="edit-description"
        opened={!!descTarget}
        initial={
          descTarget
            ? { name: descTarget.name, description: descTarget.description, is_public: descTarget.is_public }
            : { name: '', description: null, is_public: false }
        }
        submitting={descMut.isPending}
        onClose={() => setDescTarget(null)}
        onSubmit={handleEditDescription}
      />
    </Stack>
  );
}
