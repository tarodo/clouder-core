import { useState } from 'react';
import {
  Checkbox, Group, Loader, Popover, Stack, Text, TextInput, UnstyledButton,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useTags, type Tag } from '../hooks/useTags';
import { useCreateTag } from '../hooks/useCreateTag';
import { useAddTrackTag } from '../hooks/useAddTrackTag';
import { useRemoveTrackTag } from '../hooks/useRemoveTrackTag';
import { normalizeTagName } from '../lib/normalizeTagName';
import { ColorSwatchPicker } from './ColorSwatchPicker';
import { TagPill } from './TagPill';

const MAX_TAGS_PER_TRACK = 50;

export interface TrackTagsPopoverProps {
  opened: boolean;
  onClose: () => void;
  target: React.ReactElement;
  categoryId: string;
  trackId: string;
  currentTagIds: readonly string[];
}

export function TrackTagsPopover({
  opened, onClose, target, categoryId, trackId, currentTagIds,
}: TrackTagsPopoverProps) {
  const { t } = useTranslation();
  const tagsQ = useTags();
  const addMut = useAddTrackTag();
  const removeMut = useRemoveTrackTag();
  const createMut = useCreateTag();
  const [search, setSearch] = useState('');
  const [creatingColor, setCreatingColor] = useState<string | null>(null);
  const [creatingMode, setCreatingMode] = useState(false);

  const all = tagsQ.data ?? [];
  const normSearch = normalizeTagName(search);
  const visible = normSearch
    ? all.filter((tg) => normalizeTagName(tg.name).startsWith(normSearch))
    : all;
  const exactMatch = normSearch
    ? all.some((tg) => normalizeTagName(tg.name) === normSearch)
    : false;
  const showCreate = normSearch.length > 0 && !exactMatch;
  const atCap = currentTagIds.length >= MAX_TAGS_PER_TRACK;

  const toggle = async (tag: Tag, checked: boolean) => {
    try {
      if (checked) {
        await addMut.mutateAsync({
          categoryId, trackId,
          tag: { id: tag.id, name: tag.name, color: tag.color },
        });
      } else {
        await removeMut.mutateAsync({ categoryId, trackId, tagId: tag.id });
      }
    } catch {
      notifications.show({ color: 'red', message: t('tags.toast.update_failed') });
    }
  };

  const handleCreate = async () => {
    const name = search.trim();
    if (!name) return;
    try {
      const tag = await createMut.mutateAsync({ name, color: creatingColor });
      await addMut.mutateAsync({
        categoryId, trackId,
        tag: { id: tag.id, name: tag.name, color: tag.color },
      });
      setSearch('');
      setCreatingMode(false);
      setCreatingColor(null);
    } catch {
      notifications.show({ color: 'red', message: t('tags.toast.save_failed') });
    }
  };

  return (
    <Popover
      opened={opened}
      onChange={(o) => {
        if (!o) onClose();
      }}
      position="bottom-start"
      withinPortal
      shadow="md"
      width={280}
    >
      <Popover.Target>{target}</Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <TextInput
            placeholder={t('tags.popover.search_placeholder')}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
          />
          {tagsQ.isLoading && <Loader size="xs" />}
          <Stack gap={2}>
            {visible.map((tag) => {
              const checked = currentTagIds.includes(tag.id);
              return (
                <Checkbox
                  key={tag.id}
                  label={
                    <Group gap={6} wrap="nowrap">
                      <TagPill name={tag.name} color={tag.color} />
                    </Group>
                  }
                  checked={checked}
                  disabled={!checked && atCap}
                  onChange={(e) => toggle(tag, e.currentTarget.checked)}
                />
              );
            })}
            {!tagsQ.isLoading && visible.length === 0 && !showCreate && (
              <Text size="sm" c="dimmed">{t('tags.popover.empty')}</Text>
            )}
          </Stack>
          {atCap && (
            <Text size="xs" c="dimmed">{t('tags.popover.cap_hint')}</Text>
          )}
          {showCreate && !creatingMode && (
            <UnstyledButton
              onClick={() => setCreatingMode(true)}
              style={{
                fontSize: 13, padding: '4px 6px',
                borderTop: '1px solid var(--mantine-color-default-border)',
              }}
            >
              {t('tags.popover.create_label', { name: search.trim() })}
            </UnstyledButton>
          )}
          {creatingMode && (
            <Stack gap={4}>
              <ColorSwatchPicker value={creatingColor} onChange={setCreatingColor} />
              <Group justify="flex-end" gap={4}>
                <UnstyledButton
                  onClick={() => { setCreatingMode(false); setCreatingColor(null); }}
                  style={{ fontSize: 13 }}
                >
                  {t('tags.form.cancel')}
                </UnstyledButton>
                <UnstyledButton
                  onClick={handleCreate}
                  style={{ fontSize: 13, fontWeight: 600 }}
                >
                  {t('tags.popover.create_confirm')}
                </UnstyledButton>
              </Group>
            </Stack>
          )}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
