import { Button, Center, Stack, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';

export interface EmptyStateProps {
  title: string;
  body?: ReactNode;
  icon?: ReactNode;
  action?: { label: string; onClick: () => void };
}

export function EmptyState({ title, body, icon, action }: EmptyStateProps) {
  return (
    <Center mih="60vh" p="xl">
      <Stack align="center" gap="md" maw={420}>
        {icon}
        <Title order={2} ta="center">
          {title}
        </Title>
        {body &&
          (typeof body === 'string' ? (
            <Text c="dimmed" ta="center">
              {body}
            </Text>
          ) : (
            body
          ))}
        {action && (
          <Button onClick={action.onClick} variant="default">
            {action.label}
          </Button>
        )}
      </Stack>
    </Center>
  );
}
