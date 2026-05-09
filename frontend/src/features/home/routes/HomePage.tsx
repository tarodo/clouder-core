import { Alert, Button, Code, Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { ActiveBlocksList } from '../components/ActiveBlocksList';
import { CountersGrid } from '../components/CountersGrid';
import { HomeSkeleton } from '../components/HomeSkeleton';
import { NoStylesEmpty } from '../components/NoStylesEmpty';
import { ResumeHero } from '../components/ResumeHero';
import { useHomeData, type HomeData } from '../hooks/useHomeData';
import { useResumeTarget } from '../hooks/useResumeTarget';

export function HomePage() {
  const { data, isLoading, isError, error, refetchAll } = useHomeData();
  if (isLoading) return <HomeSkeleton />;
  if (isError || !data) {
    return <HomeError refetchAll={refetchAll} error={error} />;
  }
  if (data.styles.length === 0) return <NoStylesEmpty />;
  return <HomeReady data={data} refetchAll={refetchAll} />;
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

function HomeReady({ data, refetchAll }: { data: HomeData; refetchAll: () => void }) {
  const { t } = useTranslation();
  const target = useResumeTarget(data.activeBlocks, data.blocksByStyle);
  return (
    <Stack gap="md" maw={720} mx="auto" px="md">
      {data.partialError && (
        <Alert color="yellow" variant="light" title={t('home.error.partial')}>
          <Button size="xs" variant="default" onClick={refetchAll}>
            {t('home.error.partial_retry')}
          </Button>
        </Alert>
      )}
      <ResumeHero target={target} />
      <CountersGrid
        awaitingTriage={data.awaitingTriageCount}
        activeBlocks={data.activeBlocksCount}
      />
      <ActiveBlocksList blocks={data.topActiveBlocks} total={data.activeBlocksCount} />
    </Stack>
  );
}
