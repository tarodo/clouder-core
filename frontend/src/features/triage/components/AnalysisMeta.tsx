import { Box, Group, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

type Tone = 'ok' | 'warn' | 'none';

const DOT: Record<Tone, string> = {
  ok: 'var(--mantine-color-teal-6)',
  warn: 'var(--mantine-color-red-6)',
  none: 'var(--mantine-color-gray-4)',
};

function Flag({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return (
    <Group gap={4} wrap="nowrap" data-tone={tone}>
      <Text size="sm" c="var(--color-fg-muted)">
        {label}:
      </Text>
      <Box w={7} h={7} style={{ borderRadius: '50%', background: DOT[tone], flexShrink: 0 }} />
      <Text size="sm" c="var(--color-fg-muted)">
        {value}
      </Text>
    </Group>
  );
}

/** The player's meta line: did the AI detectors check the track (and flag it), and did the audio
 * profile read it. */
export function AnalysisMeta(props: {
  aiVerdict: string | null | undefined;
  aiChecked: boolean | undefined;
  profiled: boolean | undefined;
}) {
  const { t } = useTranslation();
  const ai = props.aiVerdict ? 'flagged' : props.aiChecked ? 'clean' : 'pending';
  return (
    <Group gap="md" wrap="wrap">
      <Flag
        label={t('curate.card.ai_check_label')}
        value={t(`curate.card.ai_check.${ai}`)}
        tone={ai === 'flagged' ? 'warn' : ai === 'clean' ? 'ok' : 'none'}
      />
      <Flag
        label={t('curate.card.profile_label')}
        value={t(`curate.card.profile.${props.profiled ? 'done' : 'pending'}`)}
        tone={props.profiled ? 'ok' : 'none'}
      />
    </Group>
  );
}
