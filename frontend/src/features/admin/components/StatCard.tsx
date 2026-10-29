import { Group, Paper, Stack, Text } from '@mantine/core';
import type { ReactNode } from 'react';
import { Ghost } from '../../../components/Ghost';

/** The admin stat card: a title with its status badge, a headline number with a caption (a
 * settings card has none), then whatever the card lists. The pipeline stages and the auto-ingest cards share it.
 * Inside an active GhostScope the badge, number and caption are ghost bars; the title stays. */
export function StatCard(props: {
  title: string;
  status?: ReactNode;
  value?: ReactNode;
  total?: ReactNode;
  caption?: ReactNode;
  children?: ReactNode;
}) {
  const { title, status, value, total, caption, children } = props;
  return (
    <Paper withBorder p="md" radius="md" data-card={title}>
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap" mih={22}>
          <Text fw={600}>{title}</Text>
          {status ? <Ghost>{status}</Ghost> : status}
        </Group>
        {value !== undefined && (
          <div>
            <Group gap={6} align="baseline">
              <Ghost>
                <Text fw={700} size="xl" lh={1.2}>
                  {value}
                </Text>
              </Ghost>
              {total !== undefined && (
                <Ghost>
                  <Text size="sm" c="dimmed">
                    / {total}
                  </Text>
                </Ghost>
              )}
            </Group>
            <Ghost>
              <Text size="xs" c="dimmed">
                {caption}
              </Text>
            </Ghost>
          </div>
        )}
        {children}
      </Stack>
    </Paper>
  );
}

export function Note({ children, c = 'dimmed' }: { children: ReactNode; c?: string }) {
  return (
    <Ghost>
      <Text size="xs" c={c}>
        {children}
      </Text>
    </Ghost>
  );
}
