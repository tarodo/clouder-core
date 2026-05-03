import { SimpleGrid, type SimpleGridProps } from '@mantine/core';
import { BucketCard, type BucketCardMode } from './BucketCard';
import type { TriageBucket } from '../lib/bucketLabels';

export interface BucketGridProps {
  buckets: TriageBucket[];
  styleId: string;
  blockId: string;
  mode?: BucketCardMode;
  onSelect?: (bucket: TriageBucket) => void;
  disabled?: boolean;
  cols?: SimpleGridProps['cols'];
}

export function BucketGrid({
  buckets,
  styleId,
  blockId,
  mode = 'navigate',
  onSelect,
  disabled,
  cols = { base: 1, xs: 2, md: 3 },
}: BucketGridProps) {
  return (
    <SimpleGrid cols={cols} spacing="md">
      {buckets.map((b) => (
        <BucketCard
          key={b.id}
          bucket={b}
          styleId={styleId}
          blockId={blockId}
          mode={mode}
          onSelect={onSelect}
          disabled={disabled}
        />
      ))}
    </SimpleGrid>
  );
}
