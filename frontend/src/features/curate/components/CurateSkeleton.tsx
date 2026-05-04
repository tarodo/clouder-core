import { Group, Skeleton, Stack } from '@mantine/core';

export function CurateSkeleton() {
  return (
    <Stack gap="lg" p="xl" data-testid="curate-skeleton">
      <Group align="flex-start" gap="xl" wrap="nowrap">
        <Stack gap="md" style={{ flex: 1 }}>
          <Skeleton height={32} width="60%" radius="md" />
          <Skeleton height={20} width="40%" radius="md" />
          <Skeleton height={400} radius="lg" />
        </Stack>
        <Stack gap="sm" style={{ width: 320 }}>
          <Skeleton height={64} radius="md" />
          <Skeleton height={64} radius="md" />
          <Skeleton height={64} radius="md" />
          <Skeleton height={64} radius="md" />
        </Stack>
      </Group>
    </Stack>
  );
}
