import { Stack, Title, List } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { ArtistDetail } from '../../../api/artists';

export function ArtistStylesTab({ info }: { info: ArtistDetail }) {
  const { t } = useTranslation();
  const rec = info as Record<string, unknown>;
  const primary = Array.isArray(rec.primary_styles)
    ? (rec.primary_styles.filter((s) => typeof s === 'string') as string[])
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
    </Stack>
  );
}
