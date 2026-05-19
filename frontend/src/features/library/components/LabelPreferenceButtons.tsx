import { ActionIcon, Group } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconHeart, IconHeartFilled, IconX } from '../../../components/icons';
import {
  useSetLabelPreference,
  type LabelPreference,
} from '../hooks/useSetLabelPreference';

interface Props {
  labelId: string;
  current: LabelPreference;
  size?: 'sm' | 'md';
}

export function LabelPreferenceButtons({ labelId, current, size = 'sm' }: Props) {
  const { t } = useTranslation();
  const mutation = useSetLabelPreference();

  const iconSize = size === 'md' ? 18 : 14;
  const liked = current === 'liked';
  const disliked = current === 'disliked';

  const onLike = () =>
    mutation.mutate({ labelId, status: liked ? 'none' : 'liked' });
  const onDislike = () =>
    mutation.mutate({ labelId, status: disliked ? 'none' : 'disliked' });

  return (
    <Group gap={4} wrap="nowrap">
      <ActionIcon
        variant="subtle"
        size={size}
        onClick={onLike}
        aria-label={liked ? t('library.prefs.unset_aria') : t('library.prefs.like_aria')}
      >
        {liked ? (
          <IconHeartFilled size={iconSize} color="var(--mantine-color-red-6)" />
        ) : (
          <IconHeart size={iconSize} />
        )}
      </ActionIcon>
      <ActionIcon
        variant="subtle"
        size={size}
        onClick={onDislike}
        aria-label={disliked ? t('library.prefs.unset_aria') : t('library.prefs.dislike_aria')}
      >
        <IconX
          size={iconSize}
          color={disliked ? 'var(--mantine-color-dark-9)' : undefined}
        />
      </ActionIcon>
    </Group>
  );
}
