import { Button, Center, Code, Stack, Text, Title } from '@mantine/core';
import { useRouteError, isRouteErrorResponse, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../api/error';

export function RouteErrorBoundary() {
  const error = useRouteError();
  const navigate = useNavigate();
  const { t } = useTranslation();

  let title = t('router.error_title');
  let body = t('errors.unknown');
  let correlationId: string | undefined;

  if (isRouteErrorResponse(error)) {
    title = `${error.status} ${error.statusText}`;
    body = error.data?.message ?? body;
  } else if (error instanceof ApiError) {
    title = `${error.status} ${error.code}`;
    body = error.message;
    correlationId = error.correlationId;
  } else if (error instanceof Error) {
    body = error.message;
  }

  return (
    <Center mih="80vh" p="xl">
      <Stack align="center" gap="md" maw={520}>
        <Title order={2} ta="center">
          {title}
        </Title>
        <Text c="dimmed" ta="center">
          {body}
        </Text>
        {correlationId && (
          <Code>{t('errors.correlation_id', { id: correlationId })}</Code>
        )}
        <Button onClick={() => navigate('/')} variant="default">
          {t('empty_state.back_home')}
        </Button>
      </Stack>
    </Center>
  );
}
