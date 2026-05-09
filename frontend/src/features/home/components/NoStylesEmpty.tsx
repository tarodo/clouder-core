import { Card, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export function NoStylesEmpty() {
  const { t } = useTranslation();
  return (
    <Card withBorder padding="lg" radius="md" maw={720} mx="auto">
      <Stack gap="xs">
        <Title order={3}>{t('home.no_styles.title')}</Title>
        <Text size="sm" c="dimmed">
          {t('home.no_styles.body')}
        </Text>
      </Stack>
    </Card>
  );
}
