import { Group, Title, Text, Anchor } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { LabelDetail } from '../../../api/labels';
import { countryFlag } from '../lib/countryFlag';

interface Props {
  info: LabelDetail;
  styleId: string;
}

export function LabelDetailHeader({ info, styleId }: Props) {
  const { t } = useTranslation();
  const rec = info as Record<string, unknown>;
  const labelName = typeof rec.label_name === 'string' ? rec.label_name : '';
  const country = typeof rec.country === 'string' ? rec.country : '';
  const foundedYear =
    typeof rec.founded_year === 'number' ? rec.founded_year : null;

  return (
    <>
      <Anchor component={Link} to={`/library/${styleId}`} size="sm">
        ← {t('library.detail.back_to_list', { style: styleId })}
      </Anchor>
      <Title order={2} mt="xs">
        {labelName}
      </Title>
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
