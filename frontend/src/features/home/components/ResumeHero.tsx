import { Button, Card, Group, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { ResumeTarget } from '../hooks/useResumeTarget';

export interface ResumeHeroProps {
  target: ResumeTarget;
}

export function ResumeHero({ target }: ResumeHeroProps) {
  const { t } = useTranslation();

  if (target.kind === 'curate') {
    const { session, block } = target;
    return (
      <Card withBorder padding="lg" radius="md">
        <Stack gap="xs">
          <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
            {t('home.resume.curate.title')}
          </Text>
          <Title order={3}>
            {t('home.resume.curate.context', { style: block.style_name, block: block.name })}
          </Title>
          <Text size="sm" c="dimmed">
            {block.track_count} {t('home.counters.tracks_unit')}
          </Text>
          <Group mt="sm">
            <Button
              component={Link}
              to={`/curate/${session.styleId}/${session.blockId}/${session.bucketId}`}
            >
              {t('home.resume.curate.cta')}
            </Button>
          </Group>
        </Stack>
      </Card>
    );
  }

  if (target.kind === 'triage') {
    const { block } = target;
    return (
      <Card withBorder padding="lg" radius="md">
        <Stack gap="xs">
          <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
            {t('home.resume.triage.title')}
          </Text>
          <Title order={3}>
            {t('home.resume.triage.context', { style: block.style_name, block: block.name })}
          </Title>
          <Text size="sm" c="dimmed">
            {block.track_count} {t('home.counters.tracks_unit')}
          </Text>
          <Group mt="sm">
            <Button component={Link} to={`/triage/${block.style_id}/${block.id}`}>
              {t('home.resume.triage.cta')}
            </Button>
          </Group>
        </Stack>
      </Card>
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
