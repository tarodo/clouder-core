import { Button, Center, Stack, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';

export interface EmptyStateProps {
  title: string;
  body?: ReactNode;
  icon?: ReactNode;
  action?: { label: string; onClick: () => void };
  /** 'page' = full-height (404 / route-level). 'inline' = compact, fits inside a table/section. */
  variant?: 'page' | 'inline';
}

export function EmptyState({ title, body, icon, action, variant = 'page' }: EmptyStateProps) {
  const isInline = variant === 'inline';
  return (
    <Center
      mih={isInline ? undefined : '60vh'}
      p={isInline ? undefined : 'xl'}
      py={isInline ? 'xl' : undefined}
    >
      <Stack align="center" gap="md" maw={420}>
        {icon}
        <Title order={isInline ? 3 : 2} ta="center">
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
