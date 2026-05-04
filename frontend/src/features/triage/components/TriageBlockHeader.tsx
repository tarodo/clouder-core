import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Menu,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { IconDots } from '../../../components/icons';
import type { TriageBlock } from '../hooks/useTriageBlock';
import { nextSuggestedBucket } from '../../curate/lib/nextSuggestedBucket';

dayjs.extend(relativeTime);

export interface TriageBlockHeaderProps {
  block: TriageBlock;
  onDelete: () => void;
  onFinalize: () => void;
}

export function TriageBlockHeader({ block, onDelete, onFinalize }: TriageBlockHeaderProps) {
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
            <Badge
              size="sm"
              variant={isFinalized ? 'filled' : 'light'}
              color={isFinalized ? 'neutral.9' : undefined}
            >
              {block.status}
            </Badge>
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
            {block.status === 'IN_PROGRESS' && (() => {
              const target = nextSuggestedBucket(block.buckets, '');
              if (!target) return null;
              return (
                <Button
                  component={Link}
                  to={`/curate/${block.style_id}/${block.id}/${target.id}`}
                  variant="default"
                >
                  {t('curate.triage_cta.from_block')}
                </Button>
              );
            })()}
            <Button onClick={onFinalize}>{t('triage.detail.finalize_cta')}</Button>
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
