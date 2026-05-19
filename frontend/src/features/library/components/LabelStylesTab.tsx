import { Stack, Title, Badge, Group, Text, Collapse, UnstyledButton } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import type { LabelDetail } from '../../../api/labels';

export function LabelStylesTab({ info }: { info: LabelDetail }) {
  const { t } = useTranslation();
  const [opened, { toggle }] = useDisclosure(false);
  const rec = info as Record<string, unknown>;
  const primary = Array.isArray(rec.primary_styles)
    ? (rec.primary_styles.filter((s) => typeof s === 'string') as string[])
    : [];
  const secondary = Array.isArray(rec.secondary_styles)
    ? (rec.secondary_styles.filter((s) => typeof s === 'string') as string[])
    : [];
  const aiContent = typeof rec.ai_content === 'string' ? rec.ai_content : '';
  const aiReasoning =
    typeof rec.ai_reasoning === 'string' ? rec.ai_reasoning : '';

  return (
    <Stack gap="md">
      {primary.length > 0 && (
        <>
          <Title order={5}>{t('library.detail.primary_styles')}</Title>
          <Group gap={6}>
            {primary.map((s) => <Badge key={s}>{s}</Badge>)}
          </Group>
        </>
      )}
      {secondary.length > 0 && (
        <>
          <Title order={5}>{t('library.detail.secondary_styles')}</Title>
          <Group gap={6}>
            {secondary.map((s) => <Badge key={s} variant="outline">{s}</Badge>)}
          </Group>
        </>
      )}
      {aiContent && (
        <Group gap="xs">
          <Text fw={500}>{t('library.detail.ai_content_label')}:</Text>
          <Badge color={aiContent === 'none_detected' ? 'green' : 'yellow'}>
            {aiContent}
          </Badge>
        </Group>
      )}
      {aiReasoning && (
        <>
          <UnstyledButton onClick={toggle} c="dimmed">
            {opened ? t('library.detail.ai_reasoning') : t('library.detail.ai_reasoning_collapsed')}
          </UnstyledButton>
          <Collapse expanded={opened}>
            <Text size="sm" c="dimmed">{aiReasoning}</Text>
          </Collapse>
        </>
      )}
    </Stack>
  );
}
