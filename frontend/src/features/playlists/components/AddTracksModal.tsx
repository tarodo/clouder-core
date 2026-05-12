import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Checkbox,
  Group,
  Modal,
  ScrollArea,
  Select,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useStyles } from '../../../hooks/useStyles';
import { useCategoriesByStyle } from '../../categories/hooks/useCategoriesByStyle';
import { useCategoryTracks } from '../../categories/hooks/useCategoryTracks';
import { useAddTracksToPlaylist } from '../hooks/useAddTracksToPlaylist';
import { notifications } from '@mantine/notifications';

export interface AddTracksModalProps {
  opened: boolean;
  onClose: () => void;
  playlistId: string;
  onAdded: () => void;
}

export function AddTracksModal({ opened, onClose, playlistId, onAdded }: AddTracksModalProps) {
  const { t } = useTranslation();
  const stylesQ = useStyles();
  const [styleId, setStyleId] = useState<string | null>(null);
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const categoriesQ = useCategoriesByStyle(styleId ?? '');
  const tracksQ = useCategoryTracks(categoryId ?? '', '', 'added_at', 'desc', [], 'all');
  const addMut = useAddTracksToPlaylist();

  useEffect(() => {
    if (!opened) {
      setStyleId(null);
      setCategoryId(null);
      setSearch('');
      setSelected(new Set());
    }
  }, [opened]);

  const trackItems = (tracksQ.data?.pages ?? []).flatMap((p) => p.items);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return trackItems;
    return trackItems.filter((tr) => tr.title.toLowerCase().includes(q));
  }, [trackItems, search]);

  function toggle(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  async function handleSubmit() {
    if (selected.size === 0) return;
    try {
      const res = await addMut.mutateAsync({
        playlistId,
        trackIds: Array.from(selected),
      });
      notifications.show({
        message: t('playlists.toast.tracks_added', { count: res.added.length }),
        color: 'green',
      });
      onAdded();
      onClose();
    } catch {
      notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
    }
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="lg"
      title={t('playlists.add_tracks.title')}
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        <Group gap="sm" grow>
          <Select
            label={t('playlists.add_tracks.style_label')}
            data={(stylesQ.data?.items ?? []).map((s) => ({ value: s.id, label: s.name }))}
            value={styleId}
            onChange={(v) => {
              setStyleId(v);
              setCategoryId(null);
            }}
          />
          <Select
            label={t('playlists.add_tracks.category_label')}
            data={(categoriesQ.data?.items ?? []).map((c) => ({ value: c.id, label: c.name }))}
            value={categoryId}
            onChange={setCategoryId}
            disabled={!styleId}
          />
        </Group>
        <TextInput
          placeholder={t('playlists.add_tracks.search_placeholder')}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          disabled={!categoryId}
        />
        <ScrollArea h={320}>
          <Stack gap={4}>
            {!categoryId ? null : filtered.length === 0 ? (
              <Text c="dimmed">{t('playlists.add_tracks.empty_category')}</Text>
            ) : (
              filtered.map((tr) => (
                <Checkbox
                  key={tr.id}
                  label={tr.title}
                  checked={selected.has(tr.id)}
                  onChange={() => toggle(tr.id)}
                />
              ))
            )}
          </Stack>
        </ScrollArea>
        <Group justify="space-between">
          <Text c="dimmed" size="sm">
            {t('playlists.add_tracks.selected_count', { count: selected.size })}
          </Text>
          <Group gap="sm">
            <Button variant="default" onClick={onClose} disabled={addMut.isPending}>
              {t('playlists.form.cancel')}
            </Button>
            <Button
              onClick={() => void handleSubmit()}
              loading={addMut.isPending}
              disabled={selected.size === 0}
            >
              {t('playlists.add_tracks.submit', { count: selected.size })}
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}
