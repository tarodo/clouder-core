import { Loader, Stack, Text, Overlay } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useElapsedTime } from '../lib/useElapsedTime';

interface LongOperationOverlayProps {
  active: boolean;
}

export function LongOperationOverlay({ active }: LongOperationOverlayProps) {
  const elapsed = useElapsedTime(active);
  const { t } = useTranslation();

  if (!active) return null;
  if (elapsed < 5000) return null;

  const veryLong = elapsed >= 15000;
  const copy = veryLong ? t('long_op.very_long') : t('long_op.cold_start');

  return (
    <Overlay backgroundOpacity={0.55} blur={2} center>
      <Stack align="center" gap="sm" maw={360}>
        <Loader size="md" />
        <Text ta="center">{copy}</Text>
      </Stack>
    </Overlay>
  );
}
