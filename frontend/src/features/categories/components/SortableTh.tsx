import { Table, UnstyledButton, Group, Text } from '@mantine/core';
import {
  IconArrowsSort,
  IconChevronDown,
  IconChevronUp,
} from '@tabler/icons-react';
import type { ReactNode } from 'react';
import type { SortOrder } from '../hooks/useCategoryTracks';

export interface SortableThProps {
  children: ReactNode;
  active: boolean;
  dir: SortOrder;
  onClick: () => void;
}

export function SortableTh({ children, active, dir, onClick }: SortableThProps) {
  const ariaSort = !active ? 'none' : dir === 'asc' ? 'ascending' : 'descending';
  const Icon = !active
    ? IconArrowsSort
    : dir === 'asc'
      ? IconChevronUp
      : IconChevronDown;
  return (
    <Table.Th aria-sort={ariaSort}>
      <UnstyledButton onClick={onClick} style={{ width: '100%' }}>
        <Group gap={4} wrap="nowrap">
          <Text fw={500} size="sm">
            {children}
          </Text>
          <Icon size={14} color={active ? undefined : 'var(--mantine-color-dimmed)'} />
        </Group>
      </UnstyledButton>
    </Table.Th>
  );
}
