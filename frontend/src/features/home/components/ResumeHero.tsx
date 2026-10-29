import { Button, Card, Group, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Ghost, GhostScope } from '../../../components/Ghost';
import type { ResumeTarget } from '../hooks/useResumeTarget';

export interface ResumeHeroProps {
  /** undefined while the blocks load: a ghost of the usual (triage) card. */
  target: ResumeTarget | undefined;
}

function BlockCard(props: {
  label: string;
  title: string;
  tracks: number;
  cta: string;
  to: string;
}) {
  const { t } = useTranslation();
  return (
    <Card withBorder padding="lg" radius="md">
      <Stack gap="xs">
        <Ghost>
          <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
            {props.label}
          </Text>
        </Ghost>
        <Ghost>
          <Title order={3}>{props.title}</Title>
        </Ghost>
        <Ghost>
          <Text size="sm" c="dimmed">
            {props.tracks} {t('home.counters.tracks_unit')}
          </Text>
        </Ghost>
        <Group mt="sm">
          <Ghost>
            <Button component={Link} to={props.to}>
              {props.cta}
            </Button>
          </Ghost>
        </Group>
      </Stack>
    </Card>
  );
}

export function ResumeHero({ target }: ResumeHeroProps) {
  const { t } = useTranslation();

  if (!target) {
    return (
      <GhostScope on>
        <BlockCard
          label={t('home.resume.triage.title')}
          title={t('home.resume.triage.context', { style: 'Placeholder', block: 'Week 00' })}
          tracks={30}
          cta={t('home.resume.triage.cta')}
          to="/triage"
        />
      </GhostScope>
    );
  }

  if (target.kind === 'curate') {
    const { session, block } = target;
    return (
      <BlockCard
        label={t('home.resume.curate.title')}
        title={t('home.resume.curate.context', { style: block.style_name, block: block.name })}
        tracks={block.track_count}
        cta={t('home.resume.curate.cta')}
        to={`/curate/${session.styleId}/${session.blockId}/${session.bucketId}`}
      />
    );
  }

  if (target.kind === 'triage') {
    const { block } = target;
    return (
      <BlockCard
        label={t('home.resume.triage.title')}
        title={t('home.resume.triage.context', { style: block.style_name, block: block.name })}
        tracks={block.track_count}
        cta={t('home.resume.triage.cta')}
        to={`/triage/${block.style_id}/${block.id}`}
      />
    );
  }

  return (
    <Card withBorder padding="lg" radius="md">
      <Stack gap="xs">
        <Title order={3}>{t('home.resume.empty.title')}</Title>
        <Text size="sm" c="dimmed">
          {t('home.resume.empty.body')}
        </Text>
        <Group mt="sm">
          <Button component={Link} to="/triage?create=1">
            {t('home.resume.empty.cta')}
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
