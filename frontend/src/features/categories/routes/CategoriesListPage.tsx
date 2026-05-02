import { useState } from 'react';
import { Button, Group, Stack, Title } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconPlus } from '@tabler/icons-react';
import { Navigate, useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import {
  categoriesByStyleKey,
  useCategoriesByStyle,
  type Category,
  type PaginatedCategories,
} from '../hooks/useCategoriesByStyle';
import { useStyles } from '../../../hooks/useStyles';
import { useCreateCategory } from '../hooks/useCreateCategory';
import { useRenameCategory } from '../hooks/useRenameCategory';
import { useDeleteCategory } from '../hooks/useDeleteCategory';
import { useReorderCategories } from '../hooks/useReorderCategories';
import { StyleSelector } from '../components/StyleSelector';
import { CategoriesList } from '../components/CategoriesList';
import { CategoryFormDialog } from '../components/CategoryFormDialog';
import { writeLastVisitedStyle } from '../lib/lastVisitedStyle';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { ApiError } from '../../../api/error';

export function CategoriesListPage() {
  const { styleId } = useParams<{ styleId: string }>();
  if (!styleId) return <Navigate to="/categories" replace />;
  return <CategoriesListPageInner styleId={styleId} />;
}

function CategoriesListPageInner({ styleId }: { styleId: string }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const qc = useQueryClient();

  const { data, isLoading, isError } = useCategoriesByStyle(styleId);
  const { data: stylesData } = useStyles();
  const create = useCreateCategory(styleId);
  const reorder = useReorderCategories(styleId);
  const deleteMut = useDeleteCategory(styleId);
  const styleName = stylesData?.items.find((s) => s.id === styleId)?.name ?? '';

  const [createOpen, setCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Category | null>(null);
  const [createServerError, setCreateServerError] = useState<string | undefined>();
  const [renameServerError, setRenameServerError] = useState<string | undefined>();

  const renameMut = useRenameCategory(renameTarget?.id ?? '', styleId);

  const list = data?.items ?? [];

  function changeStyle(newStyleId: string) {
    writeLastVisitedStyle(newStyleId);
    navigate(`/categories/${newStyleId}`);
  }

  async function handleCreate(input: { name: string }) {
    setCreateServerError(undefined);
    try {
      await create.mutateAsync(input);
      notifications.show({ message: t('categories.toast.created'), color: 'green' });
      setCreateOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setCreateServerError(t('categories.errors.name_conflict'));
      } else {
        notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
      }
    }
  }

  async function handleRename(input: { name: string }) {
    if (!renameTarget) return;
    setRenameServerError(undefined);
    try {
      await renameMut.mutateAsync(input);
      notifications.show({ message: t('categories.toast.renamed'), color: 'green' });
      setRenameTarget(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRenameServerError(t('categories.errors.name_conflict'));
      } else {
        notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
      }
    }
  }

  function openDelete(c: Category) {
    modals.openConfirmModal({
      title: t('categories.delete_modal.title'),
      children: t('categories.delete_modal.body', { name: c.name }),
      labels: { confirm: t('categories.delete_modal.confirm'), cancel: t('categories.delete_modal.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync(c.id);
          notifications.show({ message: t('categories.toast.deleted'), color: 'green' });
        } catch {
          notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  function onReorder(orderedIds: string[]) {
    // styleId is guaranteed non-null here: the early return above handles the undefined case
    const sid = styleId as string;
    const cur = qc.getQueryData<PaginatedCategories>(categoriesByStyleKey(sid));
    if (!cur) return;
    const byId = new Map(cur.items.map((c) => [c.id, c]));
    qc.setQueryData<PaginatedCategories>(categoriesByStyleKey(sid), {
      ...cur,
      items: orderedIds.map((id, idx) => ({ ...(byId.get(id) as Category), position: idx })),
    });
    reorder.queueOrder(orderedIds);
  }

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center">
        <Title order={1}>{t('categories.page_title')}</Title>
        <Group gap="sm">
          <StyleSelector value={styleId} onChange={changeStyle} />
          <Button leftSection={<IconPlus size={16} />} onClick={() => setCreateOpen(true)}>
            {t('categories.create_cta')}
          </Button>
        </Group>
      </Group>

      {list.length === 0 ? (
        <EmptyState
          title={t('categories.empty_state.no_categories_title')}
          body={t('categories.empty_state.no_categories_body', { style_name: styleName })}
        />
      ) : (
        <CategoriesList
          categories={list}
          onReorder={onReorder}
          onRename={(c) => setRenameTarget(c)}
          onDelete={openDelete}
        />
      )}

      <CategoryFormDialog
        mode="create"
        opened={createOpen}
        initialName=""
        submitting={create.isPending}
        onClose={() => {
          setCreateOpen(false);
          setCreateServerError(undefined);
        }}
        onSubmit={handleCreate}
        serverError={createServerError}
      />
      <CategoryFormDialog
        mode="rename"
        opened={!!renameTarget}
        initialName={renameTarget?.name ?? ''}
        submitting={renameMut.isPending}
        onClose={() => {
          setRenameTarget(null);
          setRenameServerError(undefined);
        }}
        onSubmit={handleRename}
        serverError={renameServerError}
      />
    </Stack>
  );
}
