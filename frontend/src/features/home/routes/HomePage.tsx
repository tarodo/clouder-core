import { Alert, Button, Code, Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import {
  FunnelCard,
  ListeningCard,
  TimePerTrackCard,
} from '../../analytics/components/AnalyticsCards';
import { ActiveBlocksList } from '../components/ActiveBlocksList';
import { CountersGrid } from '../components/CountersGrid';
import { NoStylesEmpty } from '../components/NoStylesEmpty';
import { ResumeHero } from '../components/ResumeHero';
import { useHomeData, type HomeData } from '../hooks/useHomeData';
import { useResumeTarget } from '../hooks/useResumeTarget';

export function HomePage() {
  const { data, isLoading, isError, error, refetchAll } = useHomeData();
  if (!isLoading && (isError || !data)) {
    return <HomeError refetchAll={refetchAll} error={error} />;
  }
  if (data?.styles.length === 0) return <NoStylesEmpty />;
  return <HomeBlocks data={data} refetchAll={refetchAll} />;
}

function HomeError({ refetchAll, error }: { refetchAll: () => void; error?: unknown }) {
  const { t } = useTranslation();
  const correlationId =
    error instanceof ApiError && error.correlationId ? error.correlationId : null;
  return (
    <Stack gap="md" maw={720} mx="auto" px="md">
      <Alert color="red" variant="light" title={t('home.error.full')}>
        <Button size="xs" variant="default" onClick={refetchAll}>
          {t('home.error.full_retry')}
        </Button>
        {correlationId && <Code mt="xs">{t('errors.correlation_id', { id: correlationId })}</Code>}
      </Alert>
    </Stack>
  );
}

/** One layout loading or loaded: each block is its own ghost until its data lands, so the
 * page never jumps (the analytics cards load on their own). */
function HomeBlocks({ data, refetchAll }: { data: HomeData | undefined; refetchAll: () => void }) {
  const { t } = useTranslation();
  return (
    <Stack gap="md" maw={720} mx="auto" px="md">
      {data?.partialError && (
        <Alert color="yellow" variant="light" title={t('home.error.partial')}>
          <Button size="xs" variant="default" onClick={refetchAll}>
            {t('home.error.partial_retry')}
          </Button>
        </Alert>
      )}
      {data ? <Resume data={data} /> : <ResumeHero target={undefined} />}
      <CountersGrid
        awaitingTriage={data?.awaitingTriageCount}
        activeBlocks={data?.activeBlocksCount}
      />
      <ActiveBlocksList blocks={data?.topActiveBlocks} total={data?.activeBlocksCount ?? 0} />
      <ListeningCard />
      <FunnelCard />
      <TimePerTrackCard />
    </Stack>
  );
}

/** Only with the blocks loaded: the target check clears a stale curate location. */
function Resume({ data }: { data: HomeData }) {
  const target = useResumeTarget(data.activeBlocks, data.blocksByStyle);
  return <ResumeHero target={target} />;
}
