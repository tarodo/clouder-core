import { Kbd, UnstyledButton } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconBolt } from '../../../components/icons';
import classes from './ForceToggle.module.css';

export interface ForceToggleProps {
  active: boolean;
  hotkeyHint: string | null;
  compact: boolean;
  onClick: () => void;
}

export function ForceToggle({ active, hotkeyHint, compact, onClick }: ForceToggleProps) {
  const { t } = useTranslation();
  const ariaLabel = active ? t('curate.force.aria_on') : t('curate.force.aria_off');
  return (
    <UnstyledButton
      onClick={onClick}
      className={classes.button}
      data-active={active ? 'true' : 'false'}
      data-compact={compact ? 'true' : 'false'}
      aria-pressed={active}
      aria-label={ariaLabel}
    >
      <IconBolt size={compact ? 14 : 16} />
      {!compact && <span className={classes.label}>{t('curate.force.button_label')}</span>}
      {hotkeyHint !== null && <Kbd>{hotkeyHint}</Kbd>}
    </UnstyledButton>
  );
}
