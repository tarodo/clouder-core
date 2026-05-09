import { SimpleGrid, Skeleton, Stack } from '@mantine/core';

export function HomeSkeleton() {
  return (
    <Stack gap="md" maw={720} mx="auto" px="md">
      <Skeleton height={88} radius="md" />
      <SimpleGrid cols={2} spacing="xs">
        <Skeleton height={72} radius="md" />
        <Skeleton height={72} radius="md" />
      </SimpleGrid>
      <Skeleton height={200} radius="md" />
    </Stack>
  );
}
