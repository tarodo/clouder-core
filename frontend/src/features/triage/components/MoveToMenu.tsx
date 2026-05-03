import { ActionIcon, Menu } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconArrowsExchange, IconDotsVertical } from '../../../components/icons';
import { bucketLabel, moveDestinationsFor, type TriageBucket } from '../lib/bucketLabels';
import { BucketBadge } from './BucketBadge';

export interface MoveToMenuProps {
  buckets: TriageBucket[];
  currentBucketId: string;
  onMove: (toBucket: TriageBucket) => void;
  onTransfer?: () => void;
  showTransfer?: boolean;
  disabled?: boolean;
}

export function MoveToMenu({
  buckets,
  currentBucketId,
  onMove,
  onTransfer,
  showTransfer,
  disabled,
}: MoveToMenuProps) {
  const { t } = useTranslation();
  const destinations = moveDestinationsFor(buckets, currentBucketId);
  const transferAvailable = !!showTransfer && !!onTransfer;

  const noItems = destinations.length === 0 && !transferAvailable;

  if (noItems || disabled) {
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
        {destinations.length > 0 && (
          <>
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
          </>
        )}
        {transferAvailable && destinations.length > 0 && <Menu.Divider />}
        {transferAvailable && (
          <Menu.Item leftSection={<IconArrowsExchange size={14} />} onClick={onTransfer}>
            {t('triage.transfer.menu_item')}
          </Menu.Item>
        )}
      </Menu.Dropdown>
    </Menu>
  );
}
