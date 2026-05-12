import { useEffect } from 'react';
import {
  Button,
  Drawer,
  Group,
  Modal,
  Stack,
  Switch,
  Textarea,
  TextInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { zodResolver } from 'mantine-form-zod-resolver';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import {
  createPlaylistSchema,
  playlistNameSchema,
  playlistDescriptionSchema,
} from '../lib/playlistSchemas';
import { translateFieldError } from '../lib/errorMessages';

export type PlaylistFormMode = 'create' | 'rename' | 'edit-description';

export interface PlaylistFormDialogProps {
  mode: PlaylistFormMode;
  opened: boolean;
  initial: { name: string; description: string | null; is_public: boolean };
  submitting: boolean;
  onClose: () => void;
  onSubmit: (input: {
    name?: string;
    description?: string | null;
    is_public?: boolean;
  }) => void;
  serverNameError?: string;
}

const renameSchema = z.object({ name: playlistNameSchema });
const editDescriptionSchema = z.object({ description: playlistDescriptionSchema });

type FormValues = {
  name: string;
  description: string;
  is_public: boolean;
};

export function PlaylistFormDialog({
  mode,
  opened,
  initial,
  submitting,
  onClose,
  onSubmit,
  serverNameError,
}: PlaylistFormDialogProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');

  const resolver =
    mode === 'create'
      ? zodResolver(createPlaylistSchema)
      : mode === 'rename'
        ? zodResolver(renameSchema)
        : zodResolver(editDescriptionSchema);

  const form = useForm<FormValues>({
    initialValues: {
      name: initial.name,
      description: initial.description ?? '',
      is_public: initial.is_public,
    },
    validate: resolver,
  });

  useEffect(() => {
    if (opened) {
      form.setValues({
        name: initial.name,
        description: initial.description ?? '',
        is_public: initial.is_public,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, initial.name, initial.description, initial.is_public]);

  const title =
    mode === 'create'
      ? t('playlists.form.create_title')
      : mode === 'rename'
        ? t('playlists.form.rename_title')
        : t('playlists.form.edit_description_title');

  const submitLabel =
    mode === 'create' ? t('playlists.form.submit_create') : t('playlists.form.submit_save');

  const nameError = serverNameError
    ?? translateFieldError(form.errors.name as string | undefined, t);

  const descriptionError = translateFieldError(
    form.errors.description as string | undefined,
    t,
  );

  function handleSubmit(values: FormValues) {
    const out: { name?: string; description?: string | null; is_public?: boolean } = {};
    if (mode === 'create' || mode === 'rename') out.name = values.name.trim();
    if (mode === 'create' || mode === 'edit-description') {
      out.description = values.description.trim() === '' ? null : values.description.trim();
    }
    if (mode === 'create') out.is_public = values.is_public;
    onSubmit(out);
  }

  const body = (
    <form onSubmit={form.onSubmit(handleSubmit)}>
      <Stack gap="md">
        {(mode === 'create' || mode === 'rename') && (
          <TextInput
            label={t('playlists.form.name_label')}
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
            maxLength={100}
            {...form.getInputProps('name')}
            error={nameError}
          />
        )}
        {(mode === 'create' || mode === 'edit-description') && (
          <Textarea
            label={t('playlists.form.description_label')}
            maxLength={300}
            autosize
            minRows={2}
            maxRows={6}
            {...form.getInputProps('description')}
            error={descriptionError}
          />
        )}
        {mode === 'create' && (
          <Switch
            label={t('playlists.form.is_public_label')}
            description={t('playlists.form.is_public_description')}
            {...form.getInputProps('is_public', { type: 'checkbox' })}
          />
        )}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            {t('playlists.form.cancel')}
          </Button>
          <Button type="submit" loading={submitting}>
            {submitLabel}
          </Button>
        </Group>
      </Stack>
    </form>
  );

  if (isMobile) {
    return (
      <Drawer opened={opened} onClose={onClose} position="bottom" size="auto" title={title}>
        {body}
      </Drawer>
    );
  }
  return (
    <Modal opened={opened} onClose={onClose} title={title} centered transitionProps={{ duration: 0 }}>
      {body}
    </Modal>
  );
}
