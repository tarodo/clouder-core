import { ActionIcon, Anchor, Group, Loader, Menu, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconDotsVertical } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useCategoriesByStyle } from '../hooks/useCategoriesByStyle';
import { useRemoveTrackOptimistic } from '../hooks/useRemoveTrackOptimistic';
import {
  MovePartialError,
  useMoveTrackBetweenCategories,
} from '../hooks/useMoveTrackBetweenCategories';
import { useAddTrackToCategory } from '../hooks/useAddTrackToCategory';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import type { CategoryTrack } from '../hooks/useCategoryTracks';

export interface TrackRowActionsProps {
  track: CategoryTrack;
  currentCategoryId: string;
  styleId: string;
}

export function TrackRowActions({ track, currentCategoryId, styleId }: TrackRowActionsProps) {
  const { t } = useTranslation();
  const categoriesQ = useCategoriesByStyle(styleId);
  const moveMut = useMoveTrackBetweenCategories();
  const removeMut = useRemoveTrackOptimistic();
  const addMut = useAddTrackToCategory();

  const allCategories = categoriesQ.data?.items ?? [];
  const others = allCategories.filter((c) => c.id !== currentCategoryId);

  const fireUndoToast = (successMsg: string, runUndo: () => Promise<void>) => {
    const toastId = `cat-track-${Date.now()}-${track.id}`;
    notifications.show({
      id: toastId,
      color: 'green',
      autoClose: 5000,
      message: (
        <Group justify="space-between" gap="md">
          <Text size="sm">{successMsg}</Text>
          <Anchor
            component="button"
            onClick={async () => {
              notifications.hide(toastId);
              try {
                await runUndo();
                notifications.show({
                  message: t('categories.toast.undone'),
                  color: 'green',
                });
              } catch {
                notifications.show({
                  message: t('categories.toast.undo_failed'),
                  color: 'red',
                });
              }
            }}
          >
            {t('categories.toast.undo_action')}
          </Anchor>
        </Group>
      ),
    });
  };

  const handleMove = async (toCategoryId: string, toCategoryName: string) => {
    try {
      await moveMut.mutateAsync({
        trackId: track.id,
        fromCategoryId: currentCategoryId,
        toCategoryId,
      });
      fireUndoToast(
        t('categories.toast.track_moved', { name: toCategoryName }),
        () =>
          moveMut.mutateAsync({
            trackId: track.id,
            fromCategoryId: toCategoryId,
            toCategoryId: currentCategoryId,
          }) as unknown as Promise<void>,
      );
    } catch (err) {
      if (err instanceof MovePartialError) {
        const partialId = `cat-track-partial-${Date.now()}-${track.id}`;
        notifications.show({
          id: partialId,
          color: 'red',
          autoClose: 8000,
          message: (
            <Group justify="space-between" gap="md">
              <Text size="sm">{t('categories.toast.track_moved_partial')}</Text>
              <Anchor
                component="button"
                onClick={async () => {
                  notifications.hide(partialId);
                  try {
                    await api(`/categories/${currentCategoryId}/tracks/${track.id}`, {
                      method: 'DELETE',
                    });
                    notifications.show({
                      message: t('categories.toast.track_removed'),
                      color: 'green',
                    });
                  } catch {
                    notifications.show({
                      message: t('categories.toast.track_remove_failed'),
                      color: 'red',
                    });
                  }
                }}
              >
                {t('categories.toast.retry')}
              </Anchor>
            </Group>
          ),
        });
      } else if (
        err instanceof ApiError &&
        err.status === 404 &&
        err.code === 'category_not_found'
      ) {
        notifications.show({
          message: t('categories.toast.category_missing'),
          color: 'red',
        });
      } else {
        notifications.show({
          message: t('categories.toast.track_move_failed'),
          color: 'red',
        });
      }
    }
  };

  const handleRemove = async () => {
    try {
      await removeMut.mutateAsync({
        categoryId: currentCategoryId,
        trackId: track.id,
      });
      fireUndoToast(
        t('categories.toast.track_removed'),
        () =>
          addMut.mutateAsync({
            categoryId: currentCategoryId,
            trackId: track.id,
          }) as unknown as Promise<void>,
      );
    } catch {
      notifications.show({
        message: t('categories.toast.track_remove_failed'),
        color: 'red',
      });
    }
  };

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon variant="subtle" aria-label={t('categories.row_actions.trigger_aria')}>
          <IconDotsVertical size={16} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>
          {categoriesQ.isLoading
            ? t('categories.row_actions.move_label')
            : others.length === 0
              ? t('categories.row_actions.move_empty')
              : t('categories.row_actions.move_label')}
        </Menu.Label>
        {categoriesQ.isLoading ? (
          <Menu.Item disabled leftSection={<Loader size={12} />}>
            {t('categories.row_actions.loading')}
          </Menu.Item>
        ) : (
          allCategories.map((c) =>
            c.id === currentCategoryId ? (
              <Menu.Item key={c.id} disabled>
                {c.name} {t('categories.row_actions.current_marker')}
              </Menu.Item>
            ) : (
              <Menu.Item key={c.id} onClick={() => handleMove(c.id, c.name)}>
                {c.name}
              </Menu.Item>
            ),
          )
        )}
        <Menu.Divider />
        <Menu.Item color="red" onClick={handleRemove}>
          {t('categories.row_actions.remove_label')}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
