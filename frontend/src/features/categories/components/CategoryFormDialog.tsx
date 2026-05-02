import { useEffect } from 'react';
import { Button, Drawer, Group, Modal, Stack, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { zodResolver } from 'mantine-form-zod-resolver';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { createCategorySchema, type CreateCategoryInput } from '../lib/categorySchemas';

export type CategoryFormMode = 'create' | 'rename';

export interface CategoryFormDialogProps {
  mode: CategoryFormMode;
  opened: boolean;
  initialName: string;
  submitting: boolean;
  onClose: () => void;
  onSubmit: (input: CreateCategoryInput) => void;
  serverError?: string;
}

export function CategoryFormDialog({
  mode,
  opened,
  initialName,
  submitting,
  onClose,
  onSubmit,
  serverError,
}: CategoryFormDialogProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const form = useForm<CreateCategoryInput>({
    initialValues: { name: initialName },
    validate: zodResolver(createCategorySchema),
  });

  useEffect(() => {
    if (opened) form.setValues({ name: initialName });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, initialName]);

  const title = mode === 'create' ? t('categories.form.create_title') : t('categories.form.rename_title');
  const submitLabel = mode === 'create' ? t('categories.form.create_submit') : t('categories.form.save');

  const errorMap: Record<string, string> = {
    name_required: t('categories.errors.name_required'),
    name_too_long: t('categories.errors.name_too_long'),
    name_control_chars: t('categories.errors.name_control_chars'),
  };
  const fieldError = (() => {
    if (serverError) return serverError;
    const e = form.errors.name;
    if (!e) return undefined;
    return errorMap[String(e)] ?? String(e);
  })();

  const body = (
    <form onSubmit={form.onSubmit((values) => onSubmit({ name: values.name.trim() }))}>
      <Stack gap="md">
        <TextInput
          label={t('categories.form.name_label')}
          description={t('categories.form.name_description')}
          placeholder={t('categories.form.name_placeholder')}
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          maxLength={64}
          {...form.getInputProps('name')}
          error={fieldError}
        />
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            {t('categories.form.cancel')}
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
