import { SimpleGrid } from '@mantine/core';
import { BucketCard } from './BucketCard';
import type { TriageBucket } from '../lib/bucketLabels';

export interface BucketGridProps {
  buckets: TriageBucket[];
  styleId: string;
  blockId: string;
}

export function BucketGrid({ buckets, styleId, blockId }: BucketGridProps) {
  return (
    <SimpleGrid cols={{ base: 1, xs: 2, md: 3 }} spacing="md">
      {buckets.map((b) => (
        <BucketCard key={b.id} bucket={b} styleId={styleId} blockId={blockId} />
      ))}
    </SimpleGrid>
  );
}
