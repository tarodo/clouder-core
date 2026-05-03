import { ActionIcon, Menu } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconDotsVertical } from '../../../components/icons';
import { bucketLabel, moveDestinationsFor, type TriageBucket } from '../lib/bucketLabels';
import { BucketBadge } from './BucketBadge';

export interface MoveToMenuProps {
  buckets: TriageBucket[];
  currentBucketId: string;
  onMove: (toBucket: TriageBucket) => void;
  disabled?: boolean;
}

export function MoveToMenu({ buckets, currentBucketId, onMove, disabled }: MoveToMenuProps) {
  const { t } = useTranslation();
  const destinations = moveDestinationsFor(buckets, currentBucketId);

  if (destinations.length === 0 || disabled) {
    return (
      <ActionIcon variant="subtle" disabled aria-label={t('triage.move.menu.trigger_aria')}>
        <IconDotsVertical size={16} />
      </ActionIcon>
    );
  }

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon variant="subtle" aria-label={t('triage.move.menu.trigger_aria')}>
          <IconDotsVertical size={16} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>{t('triage.move.menu.label')}</Menu.Label>
        {destinations.map((d) => (
          <Menu.Item
            key={d.id}
            leftSection={<BucketBadge bucket={d} size="xs" />}
            onClick={() => onMove(d)}
            aria-label={t('triage.move.menu.destination_aria', { label: bucketLabel(d, t) })}
          >
            {bucketLabel(d, t)}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
