import { Anchor, Group, Stack, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';

export interface PageHeaderProps {
  /** Page title — always rendered as an h2 (order={2}). */
  title: ReactNode;
  /** Inline back-link, detail pages only. */
  backLink?: { label: string; onClick: () => void };
  /** Inline nodes next to the title (badges, status). */
  badges?: ReactNode;
  /** Right-aligned slot (primary actions). */
  actions?: ReactNode;
  /** Muted description / metadata line under the title. */
  subtitle?: string;
  /** Bottom slot: Tabs / Filters / Toolbar. */
  children?: ReactNode;
}

export function PageHeader({ title, backLink, badges, actions, subtitle, children }: PageHeaderProps) {
  return (
    <Stack gap="xs">
      {backLink && (
        <Anchor component="button" type="button" onClick={backLink.onClick} size="sm">
          {backLink.label}
        </Anchor>
      )}
      <Group justify="space-between" align="center" wrap="wrap" gap="sm">
        <Group gap="sm" align="center" wrap="wrap">
          <Title order={2}>{title}</Title>
          {badges}
        </Group>
        {actions && <Group gap="xs">{actions}</Group>}
      </Group>
      {subtitle && (
        <Text c="dimmed" size="sm">
          {subtitle}
        </Text>
      )}
      {children}
    </Stack>
  );
}
