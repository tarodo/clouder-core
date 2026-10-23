import { useEffect, useRef } from 'react';
import {
  ActionIcon,
  Anchor,
  Button,
  Collapse,
  Drawer,
  Group,
  Modal,
  NumberInput,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useForm } from '@mantine/form';
import { zodResolver } from 'mantine-form-zod-resolver';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import {
  createTriageBlockSchema,
  type CreateTriageBlockInput as ZodInput,
} from '../lib/triageSchemas';
import {
  isoDay,
  saturdayWeekRange,
  shiftWeek,
  weekOfDate,
  type SaturdayWeek,
} from '../../../lib/saturdayWeek';
import { IconChevronLeft, IconChevronRight } from '../../../components/icons';
import { defaultTriageWeek } from '../lib/defaultTriageWeek';
import { useTriageBlocksByStyle } from '../hooks/useTriageBlocksByStyle';
import {
  useCreateTriageBlock,
  PendingCreateError,
} from '../hooks/useCreateTriageBlock';

/** Form date slot → `YYYY-MM-DD` (Mantine 9 emits strings). */
function dayOf(v: string | Date): string {
  return typeof v === 'string' ? v.slice(0, 10) : isoDay(v);
}

/** The user's local calendar day as a UTC midnight — what "this week" means to them. */
function localToday(): Date {
  const n = new Date();
  return new Date(Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()));
}

const utcDay = (day: string) => new Date(`${day}T00:00:00Z`);

const weekStartMs = ([year, week]: SaturdayWeek) => saturdayWeekRange(year, week)[0].getTime();

function fmtDay(day: string, withYear = false): string {
  return utcDay(day).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    ...(withYear ? { year: 'numeric' } : {}),
    timeZone: 'UTC',
  });
}

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
  const [advancedOpen, advanced] = useDisclosure(false);

  const form = useForm<ZodInput>({
    initialValues: {
      // Mantine 9 DatePickerInput accepts/emits string|null for range slots.
      // Use null placeholders; Zod coercion handles the string conversion on submit.
      name: '',
      dateRange: [null as unknown as Date, null as unknown as Date],
      oldOffsetWeeks: 2,
      includeDislikedLabels: true,
      includeDislikedArtists: true,
      compilationsToNot: true,
      includeFavorites: true,
      aiToDiscard: true,
    },
    validate: zodResolver(createTriageBlockSchema),
  });

  const setWeek = ([year, week]: SaturdayWeek) => {
    const [start, end] = saturdayWeekRange(year, week);
    form.setFieldValue('dateRange', [isoDay(start), isoDay(end)]);
    // Tuple errors live at `dateRange.0/1`; setFieldValue clears only the top key.
    form.clearFieldError('dateRange.0');
    form.clearFieldError('dateRange.1');
  };

  // Propose a week once per opening, after the style's blocks have loaded
  // (or failed — then it is the last finished week). Blocks created from
  // this dialog count even before the list refetch (or a 503 recovery) lands.
  // ponytail: first page = the 50 most recently created blocks; an older
  // block with a later date_to is ignored.
  const blocks = useTriageBlocksByStyle(styleId, undefined);
  const createdDateTos = useRef<Record<string, string[]>>({});
  const weekProposed = useRef(false);
  useEffect(() => {
    if (!opened || weekProposed.current || blocks.isPending || blocks.isFetching) return;
    weekProposed.current = true;
    if (form.values.dateRange?.[0]) return; // user picked a range meanwhile
    const dateTos = [
      ...(blocks.data?.pages[0]?.items.map((b) => b.date_to) ?? []),
      ...(createdDateTos.current[styleId] ?? []),
    ];
    setWeek(defaultTriageWeek(dateTos, localToday()));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, blocks.isPending, blocks.isFetching, blocks.data, styleId]);

  const [rawFrom, rawTo] = form.values.dateRange ?? [];
  const fromDay = rawFrom ? dayOf(rawFrom) : null;
  const toDay = rawTo ? dayOf(rawTo) : null;
  const week = fromDay ? weekOfDate(utcDay(fromDay)) : null;
  const currentWeek = weekOfDate(localToday());
  const atCurrentWeek = !week || weekStartMs(week) >= weekStartMs(currentWeek);

  useEffect(() => {
    if (userEditedName.current) return;
    if (!week) return;
    form.setFieldValue('name', `${styleName} W${week[1]}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [week?.[0], week?.[1], styleName]);

  let weekLabel = '—';
  if (week && fromDay && toDay) {
    const [start, end] = saturdayWeekRange(week[0], week[1]);
    weekLabel =
      fromDay === isoDay(start) && toDay === isoDay(end)
        ? `W${week[1]} · ${fmtDay(fromDay)} – ${fmtDay(toDay, true)}`
        : t('triage.form.week_custom', { range: `${fmtDay(fromDay)} – ${fmtDay(toDay, true)}` });
  }

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
    weekProposed.current = false;
    advanced.close();
    onClose();
  };

  const handleSubmit = form.onSubmit(async (values) => {
    const [from, to] = values.dateRange;
    const remember = () =>
      (createdDateTos.current[styleId] ??= []).push(dayOf(to));
    try {
      await create.mutateAsync({
        style_id: styleId,
        name: values.name.trim(),
        date_from: dayOf(from),
        date_to: dayOf(to),
        old_offset_weeks: values.oldOffsetWeeks,
        include_disliked_labels: values.includeDislikedLabels,
        include_disliked_artists: values.includeDislikedArtists,
        compilations_to_not: values.compilationsToNot,
        include_favorites: values.includeFavorites,
        ai_to_discard: values.aiToDiscard,
      });
      remember();
      notifications.show({
        message: t('triage.toast.created'),
        color: 'green',
      });
      handleClose();
    } catch (err) {
      if (err instanceof PendingCreateError) {
        remember();
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

  // Map Zod error keys to localised strings. Tuple-element errors land at
  // path `dateRange.0` / `dateRange.1` (Mantine form flattens Zod paths with
  // dots), so check those alongside the top-level key.
  const rawDateError =
    form.errors.dateRange ??
    form.errors['dateRange.0'] ??
    form.errors['dateRange.1'];
  const dateError =
    rawDateError === 'date_range_invalid'
      ? t('triage.errors.date_range_invalid')
      : rawDateError
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
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {t('triage.form.week_label')}
          </Text>
          <Group gap="xs" wrap="nowrap">
            <ActionIcon
              variant="default"
              aria-label={t('triage.form.week_prev_aria')}
              disabled={!week}
              onClick={() => week && setWeek(shiftWeek(week, -1))}
            >
              <IconChevronLeft size={16} />
            </ActionIcon>
            <Text size="sm" style={{ flex: 1, textAlign: 'center' }}>
              {weekLabel}
            </Text>
            <ActionIcon
              variant="default"
              aria-label={t('triage.form.week_next_aria')}
              disabled={atCurrentWeek}
              onClick={() => week && setWeek(shiftWeek(week, 1))}
            >
              <IconChevronRight size={16} />
            </ActionIcon>
          </Group>
          {dateError && !advancedOpen ? (
            <Text size="xs" c="red">
              {dateError}
            </Text>
          ) : null}
        </Stack>
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
        <Anchor component="button" type="button" size="sm" onClick={advanced.toggle}>
          {t('triage.form.advanced_toggle')}
        </Anchor>
        <Collapse expanded={advancedOpen}>
          <Stack gap="md">
            <DatePickerInput
              type="range"
              label={t('triage.form.date_range_label')}
              description={t('triage.form.date_range_description')}
              placeholder={t('triage.form.date_range_placeholder')}
              valueFormat="YYYY-MM-DD"
              {...form.getInputProps('dateRange')}
              error={advancedOpen ? dateError : undefined}
            />
            <NumberInput
              label={t('triage.form.old_offset_weeks_label')}
              description={t('triage.form.old_offset_weeks_description')}
              min={0}
              max={520}
              allowDecimal={false}
              {...form.getInputProps('oldOffsetWeeks')}
            />
            <Switch
              label={t('triage.form.ai_to_discard_label')}
              description={t('triage.form.ai_to_discard_description')}
              {...form.getInputProps('aiToDiscard', { type: 'checkbox' })}
            />
            <Switch
              label={t('triage.form.include_disliked_labels_label')}
              description={t('triage.form.include_disliked_labels_description')}
              {...form.getInputProps('includeDislikedLabels', { type: 'checkbox' })}
            />
            <Switch
              label={t('triage.form.include_disliked_artists_label')}
              description={t('triage.form.include_disliked_artists_description')}
              {...form.getInputProps('includeDislikedArtists', { type: 'checkbox' })}
            />
            <Switch
              label={t('triage.form.compilations_to_not_label')}
              description={t('triage.form.compilations_to_not_description')}
              {...form.getInputProps('compilationsToNot', { type: 'checkbox' })}
            />
            <Switch
              label={t('triage.form.include_favorites_label')}
              description={t('triage.form.include_favorites_description')}
              {...form.getInputProps('includeFavorites', { type: 'checkbox' })}
            />
          </Stack>
        </Collapse>
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
