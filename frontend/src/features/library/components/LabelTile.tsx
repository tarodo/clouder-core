import { Anchor, ActionIcon, Card, Group, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useLabelInfo } from '../hooks/useLabelInfo';
import { countryFlag } from '../lib/countryFlag';
import { pickTopChannels } from '../lib/pickTopChannels';
import { LabelTileSkeleton } from './LabelTileSkeleton';

interface Props {
  labelId: string | null | undefined;
  styleId: string;
}

// LabelDetail is typed as `{ [key: string]: unknown }` because the OpenAPI
// schema declares `additionalProperties: True`. Cast through a narrow shape
// for the fields the tile actually renders.
interface LabelInfoView {
  label_name?: string;
  country?: string | null;
  tagline?: string | null;
  summary?: string | null;
}

export function LabelTile({ labelId, styleId }: Props) {
  const { t } = useTranslation();
  const query = useLabelInfo(labelId);

  if (!labelId) return null;
  if (query.isLoading) return <LabelTileSkeleton />;
  if (query.isError || !query.data) return null;

  const info = query.data as LabelInfoView;
  const channels = pickTopChannels(query.data as Record<string, string | null | undefined>, 3);
  const detailUrl = `/library/${styleId}/labels/${labelId}`;

  return (
    <Card withBorder padding="md" w={320}>
      <Stack gap="xs">
        <Group gap="xs">
          {info.country && <Text>{countryFlag(info.country)}</Text>}
          <Anchor component={Link} to={detailUrl} fw={600}>
            {info.label_name}
          </Anchor>
        </Group>
        <Text size="sm" lineClamp={2}>
          {info.tagline ?? info.summary ?? ''}
        </Text>
        <Group gap={6}>
          {channels.map((ch) => (
            <ActionIcon
              key={ch.kind}
              component="a"
              href={ch.url}
              target="_blank"
              rel="noopener noreferrer"
              variant="subtle"
              aria-label={t(ch.i18nKey)}
            >
              <ch.Icon size={16} />
            </ActionIcon>
          ))}
        </Group>
        <Anchor component={Link} to={detailUrl} size="sm">
          {t('library.tile.read_more')}
        </Anchor>
      </Stack>
    </Card>
  );
}
