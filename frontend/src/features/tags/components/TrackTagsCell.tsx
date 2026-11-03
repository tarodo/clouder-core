import { Group, Tooltip } from '@mantine/core';
import { TagPill } from './TagPill';

export interface TrackTagsCellTag {
  id: string;
  name: string;
  color: string | null;
}

export interface TrackTagsCellProps {
  tags: readonly TrackTagsCellTag[];
  /** One line: the first `max` tags, the rest as a "+N" pill that names them on hover. */
  max?: number;
}

export function TrackTagsCell({ tags, max }: TrackTagsCellProps) {
  const shown = max === undefined ? tags : tags.slice(0, max);
  const rest = tags.slice(shown.length);
  return (
    <Group gap={4} wrap={max === undefined ? 'wrap' : 'nowrap'}>
      {shown.map((tag) => (
        <TagPill key={tag.id} name={tag.name} color={tag.color} />
      ))}
      {rest.length > 0 ? (
        <Tooltip label={rest.map((tag) => tag.name).join(', ')} withArrow>
          <span style={{ display: 'inline-flex' }}>
            <TagPill name={`+${rest.length}`} color={null} />
          </span>
        </Tooltip>
      ) : null}
    </Group>
  );
}
