import { Stack, Title, List } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { LabelDetail } from '../../../api/labels';

export function LabelStylesTab({ info }: { info: LabelDetail }) {
  const { t } = useTranslation();
  const rec = info as Record<string, unknown>;
  const primary = Array.isArray(rec.primary_styles)
    ? (rec.primary_styles.filter((s) => typeof s === 'string') as string[])
    : [];
  const secondary = Array.isArray(rec.secondary_styles)
    ? (rec.secondary_styles.filter((s) => typeof s === 'string') as string[])
    : [];

  return (
    <Stack gap="md">
      {primary.length > 0 && (
        <>
          <Title order={5}>{t('library.detail.primary_styles')}</Title>
          <List size="sm" spacing={4} withPadding>
            {primary.map((s) => (
              <List.Item key={s}>{s}</List.Item>
            ))}
          </List>
        </>
      )}
      {secondary.length > 0 && (
        <>
          <Title order={5}>{t('library.detail.secondary_styles')}</Title>
          <List size="sm" spacing={4} withPadding>
            {secondary.map((s) => (
              <List.Item key={s}>{s}</List.Item>
            ))}
          </List>
        </>
      )}
    </Stack>
  );
}
