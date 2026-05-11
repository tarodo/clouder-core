import { Button, Group, Stack, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { zodResolver } from 'mantine-form-zod-resolver';
import { useTranslation } from 'react-i18next';
import { createTagSchema, type CreateTagInput } from '../lib/tagSchemas';
import { ColorSwatchPicker } from './ColorSwatchPicker';

export type TagFormMode = 'create' | 'rename';

export interface TagFormFieldsProps {
  mode: TagFormMode;
  initialName: string;
  initialColor: string | null;
  submitting: boolean;
  serverError?: string;
  onCancel: () => void;
  onSubmit: (input: { name: string; color: string | null }) => void;
}

export function TagFormFields({
  mode,
  initialName,
  initialColor,
  submitting,
  serverError,
  onCancel,
  onSubmit,
}: TagFormFieldsProps) {
  const { t } = useTranslation();
  const form = useForm<CreateTagInput>({
    initialValues: { name: initialName, color: initialColor },
    validate: zodResolver(createTagSchema),
  });

  const errorMap: Record<string, string> = {
    name_required: t('tags.errors.name_required'),
    name_too_long: t('tags.errors.name_too_long'),
    name_control_chars: t('tags.errors.name_control_chars'),
    color_invalid: t('tags.errors.color_invalid'),
  };
  const fieldError = (() => {
    if (serverError) return serverError;
    const e = form.errors.name;
    if (!e) return undefined;
    return errorMap[String(e)] ?? String(e);
  })();

  return (
    <form
      onSubmit={form.onSubmit((values) =>
        onSubmit({ name: values.name.trim(), color: values.color }),
      )}
    >
      <Stack gap="xs">
        <TextInput
          label={t('tags.form.name_label')}
          placeholder={t('tags.form.name_placeholder')}
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          {...form.getInputProps('name')}
          error={fieldError}
          disabled={submitting}
        />
        <ColorSwatchPicker
          value={form.values.color ?? null}
          onChange={(c) => form.setFieldValue('color', c)}
        />
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onCancel} disabled={submitting}>
            {t('tags.form.cancel')}
          </Button>
          <Button type="submit" loading={submitting}>
            {mode === 'create' ? t('tags.form.create_submit') : t('tags.form.save')}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
