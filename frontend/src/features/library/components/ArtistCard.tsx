import { Card, Group, Text, Badge, Stack } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { ArtistSummary } from '../../../api/artists';
import { countryFlag } from '../lib/countryFlag';
import { truncateTagline } from '../lib/formatLabel';

interface Props {
  item: ArtistSummary;
}

export function ArtistCard({ item }: Props) {
  const { t } = useTranslation();
  const hasInfo = item.status === 'completed' && item.info != null;
  const primary = item.info?.primary_styles ?? [];
  const visible = primary.slice(0, 3);
  const overflow = primary.length - visible.length;

  return (
    <Card
      component={Link}
      to={`/artists/${item.id}`}
      withBorder
      padding="md"
      style={{ cursor: 'pointer', textDecoration: 'none' }}
    >
      <Group gap="xs">
        {item.info?.country && <Text>{countryFlag(item.info.country)}</Text>}
        <Text fw={600}>{item.name}</Text>
      </Group>
      {hasInfo ? (
        <Stack gap="xs" mt="sm">
          <Text size="sm" lineClamp={2}>
            {truncateTagline(item.info?.tagline)}
          </Text>
          <Group gap={4}>
            {visible.map((s) => <Badge key={s} variant="light">{s}</Badge>)}
            {overflow > 0 && <Badge variant="outline">+{overflow}</Badge>}
          </Group>
        </Stack>
      ) : (
        <Badge color="gray" mt="sm">{t('library.list.info_pending')}</Badge>
      )}
    </Card>
  );
}
