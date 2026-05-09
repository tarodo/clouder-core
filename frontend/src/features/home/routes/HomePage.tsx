import { Alert, Button, Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { RouteErrorBoundary } from '../../../components/RouteErrorBoundary';
import { ActiveBlocksList } from '../components/ActiveBlocksList';
import { CountersGrid } from '../components/CountersGrid';
import { HomeSkeleton } from '../components/HomeSkeleton';
import { NoStylesEmpty } from '../components/NoStylesEmpty';
import { ResumeHero } from '../components/ResumeHero';
import { useHomeData, type HomeData } from '../hooks/useHomeData';
import { useResumeTarget } from '../hooks/useResumeTarget';

export function HomePage() {
  const { data, isLoading, isError, refetchAll } = useHomeData();
  if (isLoading) return <HomeSkeleton />;
  if (isError || !data) return <RouteErrorBoundary />;
  if (data.styles.length === 0) return <NoStylesEmpty />;
  return <HomeReady data={data} refetchAll={refetchAll} />;
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
