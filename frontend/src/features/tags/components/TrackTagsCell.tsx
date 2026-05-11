import { useState } from 'react';
import { ActionIcon, Group, UnstyledButton } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { TagPill } from './TagPill';
import { TrackTagsPopover } from './TrackTagsPopover';

export interface TrackTagsCellTag {
  id: string;
  name: string;
  color: string | null;
}

export interface TrackTagsCellProps {
  categoryId: string;
  trackId: string;
  tags: readonly TrackTagsCellTag[];
}

export function TrackTagsCell({ categoryId, trackId, tags }: TrackTagsCellProps) {
  const { t } = useTranslation();
  const [opened, setOpened] = useState(false);
  const target = (
    <ActionIcon
      variant="subtle"
      size="sm"
      aria-label={t('tags.cell.add_aria')}
      onClick={() => setOpened((o) => !o)}
    >
      <IconPlus size={14} />
    </ActionIcon>
  );

  return (
    <Group gap={4} wrap="wrap">
      {tags.map((tag) => (
        <UnstyledButton
          key={tag.id}
          onClick={() => setOpened((o) => !o)}
          style={{ display: 'inline-flex' }}
        >
          <TagPill name={tag.name} color={tag.color} />
        </UnstyledButton>
      ))}
      <TrackTagsPopover
        opened={opened}
        onClose={() => setOpened(false)}
        target={target}
        categoryId={categoryId}
        trackId={trackId}
        currentTagIds={tags.map((t) => t.id)}
      />
    </Group>
  );
}
