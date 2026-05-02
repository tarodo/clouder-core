import { useEffect, useRef } from 'react';
import {
  Button,
  Drawer,
  Group,
  Modal,
  Stack,
  TextInput,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useForm } from '@mantine/form';
import { zodResolver } from 'mantine-form-zod-resolver';
import { useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import {
  createTriageBlockSchema,
  type CreateTriageBlockInput as ZodInput,
} from '../lib/triageSchemas';
import { isoWeekOf } from '../lib/isoWeek';
import {
  useCreateTriageBlock,
  PendingCreateError,
} from '../hooks/useCreateTriageBlock';

export interface CreateTriageBlockDialogProps {
  opened: boolean;
  onClose: () => void;
  styleId: string;
  styleName: string;
}

export function CreateTriageBlockDialog({
  opened,
  onClose,
  styleId,
  styleName,
}: CreateTriageBlockDialogProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const userEditedName = useRef(false);

  const form = useForm<ZodInput>({
    initialValues: {
      name: '',
      dateRange: [null as unknown as Date, null as unknown as Date],
    },
    validate: zodResolver(createTriageBlockSchema),
  });

  const fromDate = form.values.dateRange?.[0] ?? null;
  useEffect(() => {
    if (userEditedName.current) return;
    if (!fromDate) return;
    const week = isoWeekOf(fromDate as Date);
    form.setFieldValue('name', `${styleName} W${week}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromDate, styleName]);

  const create = useCreateTriageBlock(styleId, {
    onPendingSuccess: () =>
      notifications.show({
        message: t('triage.toast.create_eventually_succeeded'),
        color: 'green',
      }),
    onPendingFailure: () =>
      notifications.show({
        message: t('triage.toast.create_failed_to_confirm'),
        color: 'red',
      }),
  });

  const handleClose = () => {
    form.reset();
    userEditedName.current = false;
    onClose();
  };

  const handleSubmit = form.onSubmit(async (values) => {
    const [from, to] = values.dateRange;
    try {
      await create.mutateAsync({
        style_id: styleId,
        name: values.name.trim(),
        date_from: dayjs(from).format('YYYY-MM-DD'),
        date_to: dayjs(to).format('YYYY-MM-DD'),
      });
      notifications.show({
        message: t('triage.toast.created'),
        color: 'green',
      });
      handleClose();
    } catch (err) {
      if (err instanceof PendingCreateError) {
        notifications.show({
          message: t('triage.toast.create_pending'),
          color: 'yellow',
        });
        handleClose();
        return;
      }
      notifications.show({
        message: t('triage.toast.generic_error'),
        color: 'red',
      });
    }
  });

  // Map Zod error keys to localised strings; fall back to date_range_required for any
  // raw "expected date" / null-tuple noise that isn't our refinement key.
  const dateError =
    form.errors.dateRange === 'date_range_invalid'
      ? t('triage.errors.date_range_invalid')
      : form.errors.dateRange
        ? t('triage.errors.date_range_required')
        : undefined;
  const nameErrorKey = form.errors.name;
  const nameError =
    typeof nameErrorKey === 'string' && nameErrorKey.startsWith('name_')
      ? t(`triage.errors.${nameErrorKey}`)
      : nameErrorKey
        ? String(nameErrorKey)
        : undefined;

  const nameInputProps = form.getInputProps('name');

  const body = (
    <form onSubmit={handleSubmit} noValidate>
      <Stack gap="md">
        <DatePickerInput
          type="range"
          label={t('triage.form.date_range_label')}
          description={t('triage.form.date_range_description')}
          placeholder={t('triage.form.date_range_placeholder')}
          valueFormat="YYYY-MM-DD"
          {...form.getInputProps('dateRange')}
          error={dateError}
        />
        <TextInput
          label={t('triage.form.name_label')}
          description={t('triage.form.name_description')}
          placeholder={t('triage.form.name_placeholder')}
          maxLength={128}
          {...nameInputProps}
          onChange={(e) => {
            userEditedName.current = true;
            nameInputProps.onChange(e);
          }}
          error={nameError}
        />
        <Group justify="flex-end" gap="sm">
          <Button variant="subtle" onClick={handleClose} disabled={create.isPending}>
            {t('triage.form.cancel')}
          </Button>
          <Button type="submit" loading={create.isPending}>
            {t('triage.form.create_submit')}
          </Button>
        </Group>
      </Stack>
    </form>
  );

  if (isMobile) {
    return (
      <Drawer
        opened={opened}
        onClose={handleClose}
        position="bottom"
        title={t('triage.form.create_title')}
        size="auto"
        transitionProps={{ duration: 0 }}
      >
        {body}
      </Drawer>
    );
  }

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title={t('triage.form.create_title')}
      transitionProps={{ duration: 0 }}
    >
      {body}
    </Modal>
  );
}
