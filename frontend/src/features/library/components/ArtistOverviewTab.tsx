import { Stack, Text, Title, List } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { ArtistDetail } from '../../../api/artists';

export function ArtistOverviewTab({ info }: { info: ArtistDetail }) {
  const { t } = useTranslation();
  const rec = info as Record<string, unknown>;
  const tagline = typeof rec.tagline === 'string' ? rec.tagline : '';
  const summary = typeof rec.summary === 'string' ? rec.summary : '';
  const bio = typeof rec.bio === 'string' ? rec.bio : '';
  const collaborators = Array.isArray(rec.notable_collaborators)
    ? (rec.notable_collaborators.filter((a) => typeof a === 'string') as string[])
    : [];

  return (
    <Stack gap="md">
      {tagline && <Text fw={500}>{tagline}</Text>}
      {summary && (
        <Text style={{ whiteSpace: 'pre-wrap' }}>{summary}</Text>
      )}
      {bio && (
        <Text style={{ whiteSpace: 'pre-wrap' }}>{bio}</Text>
      )}
      {collaborators.length > 0 && (
        <>
          <Title order={5}>{t('library.detail.notable_collaborators')}</Title>
          <List size="sm" spacing={4} withPadding>
            {collaborators.map((a) => (
              <List.Item key={a}>{a}</List.Item>
            ))}
          </List>
        </>
      )}
    </Stack>
  );
}
