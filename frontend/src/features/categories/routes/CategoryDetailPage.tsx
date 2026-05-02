import { useState } from 'react';
import { Anchor, Breadcrumbs, Button, Group, Stack, Text, Title } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { Link, Navigate, useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { useCategoryDetail } from '../hooks/useCategoryDetail';
import { useRenameCategory } from '../hooks/useRenameCategory';
import { useDeleteCategory } from '../hooks/useDeleteCategory';
import { CategoryFormDialog } from '../components/CategoryFormDialog';
import { TracksTab } from '../components/TracksTab';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { EmptyState } from '../../../components/EmptyState';

export function CategoryDetailPage() {
  const { styleId, id } = useParams<{ styleId: string; id: string }>();
  if (!styleId || !id) return <Navigate to="/categories" replace />;
  return <CategoryDetailPageInner styleId={styleId} id={id} />;
}

function CategoryDetailPageInner({ styleId, id }: { styleId: string; id: string }) {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const { data, isLoading, isError, error } = useCategoryDetail(id);
  const renameMut = useRenameCategory(id, styleId);
  const deleteMut = useDeleteCategory(styleId);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameServerError, setRenameServerError] = useState<string | undefined>();

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <EmptyState
          title={t('errors.not_found')}
          body={
            <Anchor component={Link} to={`/categories/${styleId}`}>
              {t('categories.detail.back_to_list')}
            </Anchor>
          }
        />
      );
    }
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }
  if (!data) return null;

  const trackCountLabel = t('categories.track_count', { count: data.track_count });

  function openDelete() {
    if (!data) return;
    modals.openConfirmModal({
      title: t('categories.delete_modal.title'),
      children: t('categories.delete_modal.body', { name: data.name }),
      labels: { confirm: t('categories.delete_modal.confirm'), cancel: t('categories.delete_modal.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync(id!);
          notifications.show({ message: t('categories.toast.deleted'), color: 'green' });
          navigate(`/categories/${styleId}`);
        } catch {
          notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  async function handleRename(input: { name: string }) {
    setRenameServerError(undefined);
    try {
      await renameMut.mutateAsync(input);
      notifications.show({ message: t('categories.toast.renamed'), color: 'green' });
      setRenameOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRenameServerError(t('categories.errors.name_conflict'));
      } else {
        notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
      }
    }
  }

  return (
    <Stack gap="lg">
      <Breadcrumbs>
        <Anchor component={Link} to="/categories">
          {t('categories.page_title')}
        </Anchor>
        <Anchor component={Link} to={`/categories/${styleId}`}>
          {data.style_name}
        </Anchor>
      </Breadcrumbs>
      <Group justify="space-between" align="flex-end">
        <Stack gap={2}>
          <Title order={1}>{data.name}</Title>
          <Text c="dimmed">{trackCountLabel}</Text>
        </Stack>
        <Group gap="sm">
          <Button variant="default" onClick={() => setRenameOpen(true)}>
            {t('categories.detail.actions.rename')}
          </Button>
          <Button color="red" variant="light" onClick={openDelete}>
            {t('categories.detail.actions.delete')}
          </Button>
        </Group>
      </Group>
      <TracksTab categoryId={id} />
      <CategoryFormDialog
        mode="rename"
        opened={renameOpen}
        initialName={data.name}
        submitting={renameMut.isPending}
        onClose={() => {
          setRenameOpen(false);
          setRenameServerError(undefined);
        }}
        onSubmit={handleRename}
        serverError={renameServerError}
      />
    </Stack>
  );
}
