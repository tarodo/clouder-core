import { Anchor, Group, PasswordInput, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { bpTokenStore, useBpToken } from '../lib/bpTokenStore';

export function BpTokenInput() {
  const { t } = useTranslation();
  const token = useBpToken();
  if (token) {
    return (
      <Group justify="space-between">
        <Text size="sm">{t('admin.ingest.token_loaded')}</Text>
        <Anchor size="sm" component="button" type="button" onClick={() => bpTokenStore.clear()}>
          {t('admin.ingest.reset')}
        </Anchor>
      </Group>
    );
  }
  return (
    <PasswordInput
      label={t('admin.ingest.token_label')}
      placeholder={t('admin.ingest.token_placeholder')}
      onChange={(e) => bpTokenStore.set(e.currentTarget.value || null)}
      autoComplete="off"
      data-testid="bp-token-input"
    />
  );
}
