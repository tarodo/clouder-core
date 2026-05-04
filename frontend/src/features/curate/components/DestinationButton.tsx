import { Group, Kbd, UnstyledButton } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import classes from './DestinationButton.module.css';
import {
  bucketLabel,
  type TriageBucket,
} from '../../triage/lib/bucketLabels';

export interface DestinationButtonProps {
  bucket: TriageBucket;
  hotkeyHint: string | null;
  justTapped: boolean;
  disabled: boolean;
  onClick: () => void;
}

export function DestinationButton({
  bucket,
  hotkeyHint,
  justTapped,
  disabled,
  onClick,
}: DestinationButtonProps) {
  const { t } = useTranslation();
  const label = bucketLabel(bucket, t);

  let title: string | undefined;
  if (disabled) {
    title =
      bucket.bucket_type === 'STAGING' && bucket.inactive
        ? t('curate.destination.inactive_disabled_title')
        : t('curate.destination.self_disabled_title');
  }

  return (
    <UnstyledButton
      onClick={onClick}
      disabled={disabled}
      className={classes.button}
      data-just-tapped={justTapped ? 'true' : 'false'}
      data-disabled={disabled ? 'true' : 'false'}
      aria-label={t('curate.destination.assign_aria', { label })}
      title={title}
    >
      <Group justify="space-between" gap="md" wrap="nowrap" px="md" py="xs">
        <span className={classes.label}>{label}</span>
        {hotkeyHint !== null && <Kbd>{hotkeyHint}</Kbd>}
      </Group>
    </UnstyledButton>
  );
}
