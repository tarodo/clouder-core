import { Drawer, Stack, Text, Button, Skeleton, Alert } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { useArtistEnrichmentOptions } from '../../hooks/useArtistEnrichmentOptions';
import { useEnqueueArtistEnrichment } from '../../hooks/useEnqueueArtistEnrichment';
import { EnrichConfigForm } from './EnrichConfigForm';

interface Props {
  opened: boolean;
  onClose: () => void;
  artistIds: string[];
}

export function ArtistEnqueueDrawer({ opened, onClose, artistIds }: Props) {
  const { t } = useTranslation();
  const options = useArtistEnrichmentOptions();
  const enqueue = useEnqueueArtistEnrichment();

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
        artists: artistIds.map((artist_id) => ({ artist_id })),
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
          count: res.queued_artists, run_id: res.run_id,
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
      title={<Text span fw={600} size="lg">{t('admin_enrichment.enqueue_drawer.title', { count: artistIds.length })}</Text>}
      position="right"
      size="md"
    >
      {options.isLoading && <Skeleton height={200} />}
      {options.isError && <Alert color="red">{String(options.error)}</Alert>}
      {options.data && (
        <Stack gap="md">
          <EnrichConfigForm
            options={options.data}
            value={{ vendors, promptSlug, models, mergeModel }}
            onChange={(next) => {
              setVendors(next.vendors);
              setPromptSlug(next.promptSlug);
              setModels(next.models);
              setMergeModel(next.mergeModel);
            }}
          />
          <Button
            onClick={submit}
            loading={enqueue.isPending}
            disabled={artistIds.length === 0 || vendors.length === 0}
          >
            {enqueue.isPending
              ? t('admin_enrichment.enqueue_drawer.submit_inflight')
              : t('admin_enrichment.enqueue_drawer.submit')}
          </Button>
        </Stack>
      )}
    </Drawer>
  );
}
