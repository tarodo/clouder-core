import { Anchor, Avatar, Group, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useTrackComments } from '../hooks/useTrackComments';

interface Props {
  trackId: string;
}

const MAX_SHOWN = 5;

export function CommentsPanel({ trackId }: Props) {
  const { t } = useTranslation();
  const { data, isLoading } = useTrackComments(trackId, MAX_SHOWN);

  if (isLoading || data?.status === 'pending') {
    return (
      <Stack gap={4}>
        <Text fw={500} size="sm">{t('comments.title')}</Text>
        <Text size="sm" c="dimmed">{t('comments.pending')}</Text>
      </Stack>
    );
  }

  // failed → render nothing (no error noise in the panel)
  if (!data || data.status === 'failed') return null;

  if (data.status === 'empty' || data.status === 'disabled' || data.comments.length === 0) {
    return (
      <Stack gap={4}>
        <Text fw={500} size="sm">{t('comments.title')}</Text>
        <Text size="sm" c="dimmed">{t('comments.empty')}</Text>
      </Stack>
    );
  }

  return (
    <Stack gap="xs">
      <Text fw={500} size="sm">{t('comments.title')}</Text>
      {data.comments.slice(0, MAX_SHOWN).map((c, i) => (
        <Group key={i} gap="xs" align="flex-start" wrap="nowrap">
          <Avatar src={c.author_avatar_url ?? undefined} size="sm" radius="xl" />
          <Stack gap={0} style={{ minWidth: 0 }}>
            <Group gap={6} wrap="nowrap">
              <Text size="xs" fw={600} truncate>{c.author_name}</Text>
              {c.like_count > 0 ? (
                <Text size="xs" c="dimmed">♥ {c.like_count}</Text>
              ) : null}
            </Group>
            <Text size="sm" style={{ wordBreak: 'break-word' }}>{c.text}</Text>
          </Stack>
        </Group>
      ))}
      {data.video_url ? (
        <Anchor href={data.video_url} target="_blank" rel="noopener noreferrer" size="xs">
          {t('comments.watch_on_youtube', { count: data.comment_count })}
        </Anchor>
      ) : null}
    </Stack>
  );
}
