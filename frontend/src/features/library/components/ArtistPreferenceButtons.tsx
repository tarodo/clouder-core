import { ActionIcon, Group } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import {
  IconThumbUp,
  IconThumbUpFilled,
  IconThumbDown,
  IconThumbDownFilled,
} from '../../../components/icons';
import {
  useSetArtistPreference,
  type ArtistPreference,
} from '../hooks/useSetArtistPreference';

interface Props {
  artistId: string;
  current: ArtistPreference;
  size?: 'sm' | 'md';
}

export function ArtistPreferenceButtons({ artistId, current, size = 'sm' }: Props) {
  const { t } = useTranslation();
  const mutation = useSetArtistPreference();

  const iconSize = size === 'md' ? 18 : 14;
  const liked = current === 'liked';
  const disliked = current === 'disliked';

  const onLike = () =>
    mutation.mutate({ artistId, status: liked ? 'none' : 'liked' });
  const onDislike = () =>
    mutation.mutate({ artistId, status: disliked ? 'none' : 'disliked' });

  return (
    <Group gap={4} wrap="nowrap">
      <ActionIcon
        variant="subtle"
        size={size}
        onClick={onLike}
        aria-label={liked ? t('library.prefs.unset_aria') : t('library.prefs.like_artist_aria')}
      >
        {liked ? (
          <IconThumbUpFilled size={iconSize} color="var(--mantine-color-dark-9)" />
        ) : (
          <IconThumbUp size={iconSize} />
        )}
      </ActionIcon>
      <ActionIcon
        variant="subtle"
        size={size}
        onClick={onDislike}
        aria-label={disliked ? t('library.prefs.unset_aria') : t('library.prefs.dislike_artist_aria')}
      >
        {disliked ? (
          <IconThumbDownFilled size={iconSize} color="var(--mantine-color-dark-9)" />
        ) : (
          <IconThumbDown size={iconSize} />
        )}
      </ActionIcon>
    </Group>
  );
}
