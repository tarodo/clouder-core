import { Drawer, Stack, Title, Checkbox, Select, TextInput, Button, Badge, Group, Skeleton, Alert } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { useEnrichmentOptions } from '../../hooks/useEnrichmentOptions';
import { useEnqueueEnrichment } from '../../hooks/useEnqueueEnrichment';

interface Props {
  opened: boolean;
  onClose: () => void;
  labelIds: string[];
}

export function EnqueueDrawer({ opened, onClose, labelIds }: Props) {
  const { t } = useTranslation();
  const options = useEnrichmentOptions();
  const enqueue = useEnqueueEnrichment();

  const [vendors, setVendors] = useState<string[]>([]);
  const [promptSlug, setPromptSlug] = useState<string>('');
  const [models, setModels] = useState<Record<string, string>>({});
  const [mergeModel, setMergeModel] = useState<string>('');

  useEffect(() => {
    if (!options.data) return;
    setVendors(options.data.vendors);
    const def = options.data.prompt_versions.find((p) => p.is_default) ?? options.data.prompt_versions[0];
    if (def) setPromptSlug(def.slug ?? '');
    setModels({ ...options.data.default_models });
    setMergeModel(options.data.merge?.default_model ?? '');
  }, [options.data]);

  const promptVersion = options.data?.prompt_versions.find((p) => p.slug === promptSlug)?.version ?? '';

  const submit = async () => {
    try {
      const res = await enqueue.mutateAsync({
        labels: labelIds.map((label_id) => ({ label_id })),
        vendors: vendors as ('gemini' | 'openai' | 'tavily_deepseek')[],
        models,
        prompt_slug: promptSlug,
        prompt_version: promptVersion,
        merge_vendor: 'deepseek',
        merge_model: mergeModel,
      });
      notifications.show({
        color: 'green',
        title: t('admin_enrichment.enqueue_drawer.success_notification', {
          count: res.queued_labels, run_id: res.run_id,
        }),
        message: '',
      });
      onClose();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: t('admin_enrichment.enqueue_drawer.error_notification', {
          message: err instanceof Error ? err.message : 'unknown',
        }),
        message: '',
      });
    }
  };

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={<Title order={4}>{t('admin_enrichment.enqueue_drawer.title', { count: labelIds.length })}</Title>}
      position="right"
      size="md"
    >
      {options.isLoading && <Skeleton height={200} />}
      {options.isError && <Alert color="red">{String(options.error)}</Alert>}
      {options.data && (
        <Stack gap="md">
          <Stack gap="xs">
            <Title order={6}>{t('admin_enrichment.enqueue_drawer.vendors_label')}</Title>
            {options.data.vendors.map((v) => (
              <Checkbox
                key={v}
                label={v}
                checked={vendors.includes(v)}
                onChange={(e) =>
                  setVendors((cur) =>
                    e.currentTarget.checked ? [...cur, v] : cur.filter((x) => x !== v),
                  )
                }
              />
            ))}
          </Stack>
          <Select
            label={t('admin_enrichment.enqueue_drawer.prompt_label')}
            value={promptSlug}
            data={options.data.prompt_versions.map((p) => ({ value: p.slug ?? '', label: `${p.slug}@${p.version}` }))}
            onChange={(v) => v && setPromptSlug(v)}
          />
          <Stack gap="xs">
            <Title order={6}>{t('admin_enrichment.enqueue_drawer.models_label')}</Title>
            {vendors.map((v) => (
              <TextInput
                key={v}
                label={v}
                value={models[v] ?? ''}
                onChange={(e) =>
                  setModels((cur) => ({ ...cur, [v]: e.currentTarget.value }))
                }
              />
            ))}
          </Stack>
          <Group gap="xs" align="end">
            <Stack gap={4}>
              <Title order={6}>{t('admin_enrichment.enqueue_drawer.merge_vendor_label')}</Title>
              <Badge>deepseek</Badge>
            </Stack>
            <TextInput
              label={t('admin_enrichment.enqueue_drawer.merge_model_label')}
              value={mergeModel}
              onChange={(e) => setMergeModel(e.currentTarget.value)}
              style={{ flex: 1 }}
            />
          </Group>
          <Button onClick={submit} loading={enqueue.isPending} disabled={labelIds.length === 0 || vendors.length === 0}>
            {enqueue.isPending
              ? t('admin_enrichment.enqueue_drawer.submit_inflight')
              : t('admin_enrichment.enqueue_drawer.submit')}
          </Button>
        </Stack>
      )}
    </Drawer>
  );
}
