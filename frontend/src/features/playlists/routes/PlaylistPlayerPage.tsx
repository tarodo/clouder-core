import { Stack, ActionIcon, Group } from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';
import { useNavigate, useOutletContext, useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { PlaylistPlayerPanel } from '../components/PlaylistPlayerPanel';
import type { PlaylistDetailOutletContext } from './PlaylistDetailPage';

// This page is nested under PlaylistDetailPage; the parent owns the queue
// binding + filter state. We just render the panel and a back link.
export function PlaylistPlayerPage() {
  const { id } = useParams<{ id: string }>();
  if (!id) return <Navigate to="/playlists" replace />;
  return <PlaylistPlayerPageInner id={id} />;
}

function PlaylistPlayerPageInner({ id }: { id: string }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const ctx = useOutletContext<PlaylistDetailOutletContext | undefined>();
  const items = ctx?.items ?? [];
  return (
    <Stack gap="md" p="md">
      <Group>
        <ActionIcon
          variant="subtle"
          onClick={() => navigate(`/playlists/${id}`)}
          aria-label={t('category_player.actions.back_aria')}
        >
          <IconArrowLeft />
        </ActionIcon>
      </Group>
      <PlaylistPlayerPanel playlistId={id} items={items} />
    </Stack>
  );
}
