import { Card, Skeleton } from '@mantine/core';

export function LabelTileSkeleton() {
  return (
    <Card withBorder padding="md" w={320}>
      <Skeleton height={20} mb="sm" />
      <Skeleton height={32} mb="sm" />
      <Skeleton height={24} />
    </Card>
  );
}
