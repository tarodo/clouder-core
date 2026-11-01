import { ActionIcon } from '@mantine/core';
import { IconBroadcast } from '@tabler/icons-react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';

/** Opens the tracks that sound like *trackId*: the song-radio icon beside the Spotify link. */
export function SimilarLink({ trackId, title }: { trackId: string; title: string }) {
  const { t } = useTranslation();
  const label = t('similar.open_aria', { title });
  return (
    <ActionIcon
      component={Link}
      to={`/similar/${trackId}`}
      variant="subtle"
      radius="xl"
      size="md"
      aria-label={label}
      title={label}
    >
      <IconBroadcast size={16} />
    </ActionIcon>
  );
}
