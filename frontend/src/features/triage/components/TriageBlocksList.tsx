import { Button, Loader, Stack, Tabs, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import {
  useTriageBlocksByStyle,
  type TriageStatus,
  type TriageBlockSummary,
} from '../hooks/useTriageBlocksByStyle';
import { useDeleteTriageBlock } from '../hooks/useDeleteTriageBlock';
import { TriageBlockRow } from './TriageBlockRow';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { IconLayoutColumns } from '../../../components/icons';

type TabKey = 'active' | 'finalized' | 'all';

const STATUS_FOR_TAB: Record<TabKey, TriageStatus | undefined> = {
  active: 'IN_PROGRESS',
  finalized: 'FINALIZED',
  all: undefined,
};

const TIME_FIELD_FOR_TAB: Record<TabKey, 'created_at' | 'finalized_at'> = {
  active: 'created_at',
  finalized: 'finalized_at',
  all: 'created_at',
};

export interface TriageBlocksListProps {
  styleId: string;
}

export function TriageBlocksList({ styleId }: TriageBlocksListProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabKey>('active');

  const active = useTriageBlocksByStyle(styleId, 'IN_PROGRESS');
  const finalized = useTriageBlocksByStyle(styleId, 'FINALIZED');
  const all = useTriageBlocksByStyle(styleId, undefined);

  const queries: Record<TabKey, typeof active> = {
    active,
    finalized,
    all,
  };

  const totals: Record<TabKey, number | undefined> = {
    active: active.data?.pages[0]?.total,
    finalized: finalized.data?.pages[0]?.total,
    all: all.data?.pages[0]?.total,
  };

  const deleteMutation = useDeleteTriageBlock(styleId);

  const handleDelete = (block: TriageBlockSummary) => {
    modals.openConfirmModal({
      title: t('triage.delete_modal.title'),
      children: <Text>{t('triage.delete_modal.body', { name: block.name })}</Text>,
      labels: {
        confirm: t('triage.delete_modal.confirm'),
        cancel: t('triage.delete_modal.cancel'),
      },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMutation.mutateAsync(block.id);
          notifications.show({ message: t('triage.toast.deleted'), color: 'green' });
        } catch (err) {
          if (err instanceof ApiError && err.code === 'triage_block_not_found') {
            notifications.show({
              message: t('triage.toast.delete_not_found'),
              color: 'yellow',
            });
            return;
          }
          notifications.show({
            message: t('triage.toast.generic_error'),
            color: 'red',
          });
        }
      },
    });
  };

  const counterLabel = (label: string, value: number | undefined) =>
    value === undefined ? (
      <Loader size="xs" />
    ) : (
      t('triage.tabs.counter', { label, count: value })
    );

  return (
    <Tabs value={tab} onChange={(v) => v && setTab(v as TabKey)}>
      <Tabs.List>
        <Tabs.Tab value="active">
          {counterLabel(t('triage.tabs.active'), totals.active)}
        </Tabs.Tab>
        <Tabs.Tab value="finalized">
          {counterLabel(t('triage.tabs.finalized'), totals.finalized)}
        </Tabs.Tab>
        <Tabs.Tab value="all">
          {counterLabel(t('triage.tabs.all'), totals.all)}
        </Tabs.Tab>
      </Tabs.List>

      {(Object.keys(STATUS_FOR_TAB) as TabKey[]).map((key) => {
        const q = queries[key];
        const items = q.data?.pages.flatMap((p) => p.items) ?? [];
        const remaining = q.data
          ? (q.data.pages[0]?.total ?? 0) - items.length
          : 0;
        return (
          <Tabs.Panel value={key} key={key} pt="md">
            {q.isLoading ? (
              <Loader />
            ) : items.length === 0 ? (
              <EmptyState
                icon={<IconLayoutColumns size={32} />}
                title={t(emptyTitleKey(key))}
                body={t(emptyBodyKey(key))}
              />
            ) : (
              <Stack gap={0}>
                {items.map((block) => (
                  <TriageBlockRow
                    key={block.id}
                    block={block}
                    styleId={styleId}
                    timeField={TIME_FIELD_FOR_TAB[key]}
                    onDelete={handleDelete}
                  />
                ))}
                {q.hasNextPage && (
                  <Button
                    variant="subtle"
                    onClick={() => q.fetchNextPage()}
                    loading={q.isFetchingNextPage}
                    mt="md"
                    style={{ alignSelf: 'center' }}
                  >
                    {t('triage.load_more', { remaining })}
                  </Button>
                )}
              </Stack>
            )}
          </Tabs.Panel>
        );
      })}
    </Tabs>
  );
}

function emptyTitleKey(tab: TabKey): string {
  return tab === 'active'
    ? 'triage.empty_state.no_active_title'
    : tab === 'finalized'
      ? 'triage.empty_state.no_finalized_title'
      : 'triage.empty_state.no_blocks_title';
}

function emptyBodyKey(tab: TabKey): string {
  return tab === 'active'
    ? 'triage.empty_state.no_active_body'
    : tab === 'finalized'
      ? 'triage.empty_state.no_finalized_body'
      : 'triage.empty_state.no_blocks_body';
}
