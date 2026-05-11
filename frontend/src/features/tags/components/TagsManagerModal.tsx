import { useState } from 'react';
import {
  ActionIcon, Button, Group, Loader, Modal, Stack, Text, TextInput,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconEdit, IconPlus, IconTrash, IconSearch } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { useTags, type Tag } from '../hooks/useTags';
import { useCreateTag } from '../hooks/useCreateTag';
import { useRenameTag } from '../hooks/useRenameTag';
import { useDeleteTag } from '../hooks/useDeleteTag';
import { normalizeTagName } from '../lib/normalizeTagName';
import { TagPill } from './TagPill';
import { TagFormFields } from './TagFormFields';

export interface TagsManagerModalProps {
  opened: boolean;
  onClose: () => void;
}

type EditState =
  | { mode: 'idle' }
  | { mode: 'creating' }
  | { mode: 'renaming'; tag: Tag };

export function TagsManagerModal({ opened, onClose }: TagsManagerModalProps) {
  const { t } = useTranslation();
  const tagsQ = useTags();
  const createMut = useCreateTag();
  const renameMut = useRenameTag();
  const deleteMut = useDeleteTag();
  const [edit, setEdit] = useState<EditState>({ mode: 'idle' });
  const [search, setSearch] = useState('');
  const [serverError, setServerError] = useState<string | undefined>();

  const items = (tagsQ.data ?? []).filter((tag) =>
    !search ? true : normalizeTagName(tag.name).startsWith(normalizeTagName(search)),
  );

  const handleCreate = async (input: { name: string; color: string | null }) => {
    setServerError(undefined);
    try {
      await createMut.mutateAsync(input);
      setEdit({ mode: 'idle' });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'tag_name_conflict') {
        setServerError(t('tags.errors.name_conflict'));
        return;
      }
      notifications.show({ color: 'red', message: t('tags.toast.save_failed') });
    }
  };

  const handleRename = async (tag: Tag, input: { name: string; color: string | null }) => {
    setServerError(undefined);
    try {
      await renameMut.mutateAsync({
        tagId: tag.id,
        patch: {
          name: input.name === tag.name ? undefined : input.name,
          color: input.color === tag.color ? undefined : input.color,
        },
      });
      setEdit({ mode: 'idle' });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'tag_name_conflict') {
        setServerError(t('tags.errors.name_conflict'));
        return;
      }
      notifications.show({ color: 'red', message: t('tags.toast.save_failed') });
    }
  };

  const handleDelete = (tag: Tag) => {
    modals.openConfirmModal({
      title: t('tags.delete_modal.title'),
      children: <Text size="sm">{t('tags.delete_modal.body', { name: tag.name })}</Text>,
      labels: { confirm: t('tags.delete_modal.confirm'), cancel: t('tags.delete_modal.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync({ tagId: tag.id });
        } catch {
          notifications.show({ color: 'red', message: t('tags.toast.delete_failed') });
        }
      },
    });
  };

  return (
    <Modal opened={opened} onClose={onClose} size="lg" title={t('tags.manager.title')}>
      <Stack gap="md">
        <Group justify="space-between">
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => setEdit({ mode: 'creating' })}
            disabled={edit.mode !== 'idle'}
          >
            {t('tags.manager.new_tag')}
          </Button>
          <TextInput
            placeholder={t('tags.manager.search_placeholder')}
            leftSection={<IconSearch size={14} />}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            style={{ width: 240 }}
          />
        </Group>

        {edit.mode === 'creating' && (
          <TagFormFields
            mode="create"
            initialName=""
            initialColor={null}
            submitting={createMut.isPending}
            serverError={serverError}
            onCancel={() => { setEdit({ mode: 'idle' }); setServerError(undefined); }}
            onSubmit={handleCreate}
          />
        )}

        {tagsQ.isLoading && <Loader size="sm" />}

        <Stack gap={4}>
          {items.map((tag) => (
            <Group key={tag.id} justify="space-between" wrap="nowrap">
              {edit.mode === 'renaming' && edit.tag.id === tag.id ? (
                <TagFormFields
                  mode="rename"
                  initialName={tag.name}
                  initialColor={tag.color}
                  submitting={renameMut.isPending}
                  serverError={serverError}
                  onCancel={() => { setEdit({ mode: 'idle' }); setServerError(undefined); }}
                  onSubmit={(input) => handleRename(tag, input)}
                />
              ) : (
                <>
                  <TagPill name={tag.name} color={tag.color} />
                  <Group gap={4}>
                    <ActionIcon
                      variant="subtle"
                      aria-label={t('tags.manager.rename_aria', { name: tag.name })}
                      onClick={() => setEdit({ mode: 'renaming', tag })}
                    >
                      <IconEdit size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={t('tags.manager.delete_aria', { name: tag.name })}
                      onClick={() => handleDelete(tag)}
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                </>
              )}
            </Group>
          ))}
          {!tagsQ.isLoading && items.length === 0 && (
            <Text size="sm" c="dimmed">{t('tags.manager.empty')}</Text>
          )}
        </Stack>
      </Stack>
    </Modal>
  );
}
