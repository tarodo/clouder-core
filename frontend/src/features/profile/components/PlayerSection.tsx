import { SegmentedControl, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { usePlayerScrubber, type ScrubberMode } from '../../playback/usePlayerScrubber';

export function PlayerSection() {
  const { t } = useTranslation();
  const [scrubber, setScrubber] = usePlayerScrubber();
  return (
    <Stack gap="md">
      <div>
        <Title order={4}>{t('profile.player.title')}</Title>
        <Text size="sm" c="dimmed">
          {t('profile.player.description')}
        </Text>
      </div>
      <SegmentedControl
        aria-label={t('profile.player.scrubber_aria')}
        value={scrubber}
        onChange={(v) => setScrubber(v as ScrubberMode)}
        data={[
          { value: 'waveform', label: t('profile.player.waveform') },
          { value: 'progress', label: t('profile.player.progress') },
        ]}
        style={{ alignSelf: 'flex-start' }}
      />
    </Stack>
  );
}
