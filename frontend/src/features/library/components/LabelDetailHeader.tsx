import { Group, Title, Text, Anchor, Badge, Tooltip } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { LabelDetail } from '../../../api/labels';
import { countryFlag } from '../lib/countryFlag';

interface Props {
  info: LabelDetail;
  styleId: string;
}

const AI_COLOR: Record<string, string> = {
  none_detected: 'green',
  unknown: 'gray',
  suspected: 'yellow',
  confirmed: 'red',
};

function formatAiContent(value: string): string {
  return `AI ${value.toUpperCase()}`;
}

export function LabelDetailHeader({ info, styleId }: Props) {
  const { t } = useTranslation();
  const rec = info as Record<string, unknown>;
  const labelName = typeof rec.label_name === 'string' ? rec.label_name : '';
  const country = typeof rec.country === 'string' ? rec.country : '';
  const foundedYear =
    typeof rec.founded_year === 'number' ? rec.founded_year : null;
  const aiContent = typeof rec.ai_content === 'string' ? rec.ai_content : '';
  const aiReasoning =
    typeof rec.ai_reasoning === 'string' ? rec.ai_reasoning : '';

  const aiBadge = aiContent ? (
    <Tooltip
      label={aiReasoning || t('library.detail.ai_reasoning_missing')}
      multiline
      w={340}
      withinPortal
      events={{ hover: true, focus: true, touch: true }}
      styles={{
        tooltip: {
          backgroundColor: 'white',
          color: 'black',
          padding: '12px 16px',
          lineHeight: 1.5,
          border: '1px solid var(--mantine-color-gray-3)',
          boxShadow: 'var(--mantine-shadow-md)',
        },
      }}
    >
      <Badge
        color={AI_COLOR[aiContent] ?? 'gray'}
        variant="light"
        style={{ cursor: 'help' }}
      >
        {formatAiContent(aiContent)}
      </Badge>
    </Tooltip>
  ) : null;

  return (
    <>
      <Anchor component={Link} to={`/library/${styleId}`} size="sm">
        ← {t('library.detail.back_to_list', { style: styleId })}
      </Anchor>
      <Group gap="sm" mt="xs" align="center" wrap="wrap">
        <Title order={2}>{labelName}</Title>
        {aiBadge}
      </Group>
      <Group gap="xs" mt="xs">
        {country && (
          <Text>
            {countryFlag(country)} {country}
          </Text>
        )}
        {foundedYear !== null && (
          <Text c="dimmed">
            · {t('library.detail.founded', { year: foundedYear })}
          </Text>
        )}
      </Group>
    </>
  );
}
