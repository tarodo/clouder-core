import { Group, Title, Text, Anchor, Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useBackOrFallback } from '../hooks/useBackOrFallback';
import type { LabelDetail } from '../../../api/labels';
import { countryFlag } from '../lib/countryFlag';
import { LabelPreferenceButtons } from './LabelPreferenceButtons';
import { useAuth } from '../../../auth/useAuth';
import { useEnrichLabelAuto } from '../hooks/useEnrichLabelAuto';

interface Props {
  info: LabelDetail;
  labelId: string;
}

export function LabelDetailHeader({ info, labelId }: Props) {
  const { t } = useTranslation();
  const goBack = useBackOrFallback('/library');
  const { state } = useAuth();
  const isAdmin = state.status === 'authenticated' && state.user.is_admin;
  const enrich = useEnrichLabelAuto();
  const rec = info as Record<string, unknown>;
  const labelName = typeof rec.label_name === 'string' ? rec.label_name : '';
  const country = typeof rec.country === 'string' ? rec.country : '';
  const foundedYear = typeof rec.founded_year === 'number' ? rec.founded_year : null;
  const myPreference =
    rec.my_preference === 'liked' || rec.my_preference === 'disliked' ? rec.my_preference : null;

  return (
    <>
      <Group gap="sm" align="center" wrap="wrap">
        <Anchor component="button" type="button" onClick={goBack} size="sm">
          {t('library.detail.back')}
        </Anchor>
        <Title order={2}>{labelName}</Title>
        <LabelPreferenceButtons labelId={labelId} current={myPreference} size="md" />
        {isAdmin && (
          <Button
            size="xs"
            variant="light"
            loading={enrich.isPending}
            onClick={() => enrich.mutate({ labelId })}
          >
            {t('library.detail.admin_search_now')}
          </Button>
        )}
      </Group>
      <Group gap="xs" mt="xs">
        {country && (
          <Text>
            {countryFlag(country)} {country}
          </Text>
        )}
        {foundedYear !== null && (
          <Text c="dimmed">· {t('library.detail.founded', { year: foundedYear })}</Text>
        )}
      </Group>
    </>
  );
}
