import { Stack, ActionIcon, Group } from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';
import { useNavigate, useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { CategoryPlayerPanel } from '../components/CategoryPlayerPanel';

// This page is nested under CategoryDetailPage; the parent owns the queue
// binding + filter state. We just render the panel and a back link.
export function CategoryPlayerPage() {
  const { styleId, id } = useParams<{ styleId: string; id: string }>();
  if (!styleId || !id) return <Navigate to="/categories" replace />;
  return <CategoryPlayerPageInner styleId={styleId} id={id} />;
}

function CategoryPlayerPageInner({ styleId, id }: { styleId: string; id: string }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  return (
    <Stack gap="md" p="md">
      <Group>
        <ActionIcon
          variant="subtle"
          onClick={() => navigate(`/categories/${styleId}/${id}`)}
          aria-label={t('category_player.actions.back_aria')}
        >
          <IconArrowLeft />
        </ActionIcon>
      </Group>
      <CategoryPlayerPanel categoryId={id} styleId={styleId} />
    </Stack>
  );
}
