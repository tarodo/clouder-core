import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Menu,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { IconDots } from '../../../components/icons';
import type { TriageBlock } from '../hooks/useTriageBlock';

dayjs.extend(relativeTime);

export interface TriageBlockHeaderProps {
  block: TriageBlock;
  onDelete: () => void;
}

export function TriageBlockHeader({ block, onDelete }: TriageBlockHeaderProps) {
  const { t } = useTranslation();
  const isFinalized = block.status === 'FINALIZED';

  return (
    <Stack gap="sm">
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Stack gap={2}>
          <Title order={2}>{block.name}</Title>
          <Group gap="xs" wrap="wrap">
            <Text c="dimmed" size="sm">
              {t('triage.detail.header.date_range', {
                from: block.date_from,
                to: block.date_to,
              })}
            </Text>
            <Badge variant={isFinalized ? 'light' : 'filled'}>{block.status}</Badge>
            <Text c="dimmed" size="sm">
              {t('triage.detail.header.created', { relative: dayjs(block.created_at).fromNow() })}
            </Text>
            {isFinalized && block.finalized_at && (
              <Text c="dimmed" size="sm">
                {t('triage.detail.header.finalized', {
                  relative: dayjs(block.finalized_at).fromNow(),
                })}
              </Text>
            )}
          </Group>
        </Stack>
        {!isFinalized && (
          <Group gap="xs">
            <Tooltip label={t('triage.detail.finalize_coming_soon')}>
              <Button disabled>{t('triage.detail.finalize_cta')}</Button>
            </Tooltip>
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <ActionIcon variant="subtle" aria-label={t('triage.detail.kebab.delete')}>
                  <IconDots size={16} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item color="red" onClick={onDelete}>
                  {t('triage.detail.kebab.delete')}
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        )}
      </Group>
    </Stack>
  );
}
