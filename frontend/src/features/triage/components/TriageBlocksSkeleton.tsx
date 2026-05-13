import { Group, Skeleton, Stack } from '@mantine/core';

export interface TriageBlocksSkeletonProps {
  /** How many placeholder rows to draw. Default 4 — matches the
   *  visible window before the user starts scrolling. */
  rows?: number;
}

export function TriageBlocksSkeleton({ rows = 4 }: TriageBlocksSkeletonProps) {
  return (
    <Stack gap={0} aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }).map((_, i) => (
        <Group
          key={i}
          justify="space-between"
          wrap="nowrap"
          px="md"
          py="sm"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <Stack gap={6} style={{ flex: 1, minWidth: 0 }}>
            <Skeleton height={16} width="40%" radius="sm" />
            <Skeleton height={12} width="25%" radius="sm" />
          </Stack>
          <Group gap="sm" wrap="nowrap">
            <Skeleton height={22} width={72} radius="sm" />
            <Skeleton height={28} width={28} circle />
          </Group>
        </Group>
      ))}
    </Stack>
  );
}
