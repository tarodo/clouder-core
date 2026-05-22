import { Group } from '@mantine/core';
import { TagPill } from './TagPill';

export interface TrackTagsCellTag {
  id: string;
  name: string;
  color: string | null;
}

export interface TrackTagsCellProps {
  tags: readonly TrackTagsCellTag[];
}

export function TrackTagsCell({ tags }: TrackTagsCellProps) {
  return (
    <Group gap={4} wrap="wrap">
      {tags.map((tag) => (
        <TagPill key={tag.id} name={tag.name} color={tag.color} />
      ))}
    </Group>
  );
}
