import { Stack, Text, Title, Badge, Group } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { LabelDetail } from '../../../api/labels';

export function LabelOverviewTab({ info }: { info: LabelDetail }) {
  const { t } = useTranslation();
  const rec = info as Record<string, unknown>;
  const tagline = typeof rec.tagline === 'string' ? rec.tagline : '';
  const summary = typeof rec.summary === 'string' ? rec.summary : '';
  const notable = Array.isArray(rec.notable_artists)
    ? (rec.notable_artists.filter((a) => typeof a === 'string') as string[])
    : [];

  return (
    <Stack gap="md">
      {tagline && <Text fw={500}>{tagline}</Text>}
      {summary && (
        <Text style={{ whiteSpace: 'pre-wrap' }}>{summary}</Text>
      )}
      {notable.length > 0 && (
        <>
          <Title order={5}>{t('library.detail.notable_artists')}</Title>
          <Group gap={6}>
            {notable.map((a) => <Badge key={a} variant="outline">{a}</Badge>)}
          </Group>
        </>
      )}
    </Stack>
  );
}
