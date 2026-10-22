import {
  ActionIcon, Alert, Button, Group, Loader, Paper, Stack, Text, Tooltip,
} from '@mantine/core';
import { IconBrandSpotify, IconCheck, IconExternalLink } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router';
import { PageHeader } from '../../../components/PageHeader';
import { formatLength } from '../../../lib/formatters';
import classes from './AdminYoutubeReviewPage.module.css';
import {
  useResolveYoutubeReview, useYoutubeReview, type ReviewCell, type YoutubeReviewTrack,
} from '../hooks/useYoutubeReview';

/** One Coverage cell's open YT Music reviews: our track on the left, the
 *  stored YouTube candidates on the right; pick one or mark it not on YouTube. */
export function AdminYoutubeReviewPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const cell: ReviewCell = {
    styleId: Number(params.get('style')),
    weekYear: Number(params.get('year')),
    weekNumber: Number(params.get('week')),
  };
  const q = useYoutubeReview(cell);
  const resolve = useResolveYoutubeReview(cell);

  return (
    <Stack>
      <PageHeader
        title={t('admin.youtube_review.title')}
        backLink={{ label: t('admin.youtube_review.back'), onClick: () => navigate('/admin/coverage') }}
        subtitle={
          q.data?.style_name
            ? t('admin.youtube_review.subtitle', {
                style: q.data.style_name, week: cell.weekNumber, count: q.data.tracks.length,
              })
            : undefined
        }
      />
      {q.isLoading && <Loader size="sm" />}
      {q.isError && <Alert color="red">{t('admin.youtube_review.load_failed')}</Alert>}
      {q.data && q.data.tracks.length === 0 && (
        <Text c="dimmed">{t('admin.youtube_review.empty')}</Text>
      )}
      <div className={classes.cards}>
        {q.data?.tracks.map((track) => (
          <TrackReview
            key={track.track_id}
            track={track}
            busy={resolve.isPending && resolve.variables?.trackId === track.track_id}
            onPick={(vendorTrackId) =>
              resolve.mutate({ trackId: track.track_id, action: 'accept', vendorTrackId })}
            onReject={() => resolve.mutate({ trackId: track.track_id, action: 'reject' })}
          />
        ))}
      </div>
    </Stack>
  );
}

function TrackReview({ track, busy, onPick, onReject }: {
  track: YoutubeReviewTrack;
  busy: boolean;
  onPick: (vendorTrackId: string) => void;
  onReject: () => void;
}) {
  const { t } = useTranslation();
  const title = track.mix_name ? `${track.title} (${track.mix_name})` : track.title;
  return (
    <Paper component="article" aria-label={track.title} withBorder p="xs">
      <Group gap={6} wrap="nowrap" mb={6} style={{ minWidth: 0 }}>
        {track.spotify_url && (
          <Tooltip label={t('admin.youtube_review.open_spotify')}>
            <ActionIcon component="a" href={track.spotify_url} target="_blank" size="sm"
              rel="noopener noreferrer" variant="subtle" color="green"
              aria-label={t('admin.youtube_review.open_spotify')}>
              <IconBrandSpotify size={16} />
            </ActionIcon>
          </Tooltip>
        )}
        <Text fw={600} size="sm" truncate style={{ minWidth: 0 }}>{title}</Text>
        <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          {track.artists} · {formatLength(track.length_ms)}
        </Text>
      </Group>
      <div className={classes.slots}>
        {track.candidates.length === 0 && (
          <Text size="xs" c="dimmed">{t('admin.youtube_review.no_candidates')}</Text>
        )}
        {track.candidates.map((c) => (
          <Group key={c.vendor_track_id} gap={4} wrap="nowrap" justify="space-between"
            style={{ minWidth: 0 }}>
            <Stack gap={0} style={{ minWidth: 0 }}>
              <Text size="xs" fw={500} truncate>{c.title}</Text>
              <Text size="xs" c="dimmed" truncate>
                {c.artists.join(', ')} · {formatLength(c.duration_ms)}
                {c.score != null ? ` · ${c.score.toFixed(2)}` : ''}
              </Text>
            </Stack>
            <Group gap={2} wrap="nowrap">
              <Tooltip label={t('admin.youtube_review.pick')}>
                <ActionIcon variant="light" color="green" size="sm" disabled={busy}
                  aria-label={t('admin.youtube_review.pick')}
                  onClick={() => onPick(c.vendor_track_id)}>
                  <IconCheck size={14} />
                </ActionIcon>
              </Tooltip>
              <Tooltip label={t('admin.youtube_review.open_youtube')}>
                <ActionIcon component="a" href={c.url} target="_blank" rel="noopener noreferrer"
                  variant="subtle" size="sm" aria-label={t('admin.youtube_review.open_youtube')}>
                  <IconExternalLink size={14} />
                </ActionIcon>
              </Tooltip>
            </Group>
          </Group>
        ))}
        <Button className={classes.reject} size="compact-xs" variant="subtle" color="gray"
          disabled={busy} onClick={onReject}>
          {t('admin.youtube_review.not_on_youtube')}
        </Button>
      </div>
    </Paper>
  );
}
