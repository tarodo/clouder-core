import { useEffect, useState } from 'react';
import { Tabs, Stack, Switch, Button, Title, Skeleton, Alert, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useAutoEnrichConfig } from '../hooks/useAutoEnrichConfig';
import { useSaveAutoEnrichConfig } from '../hooks/useSaveAutoEnrichConfig';
import { EnrichConfigForm, type EnrichConfigValue } from '../components/enrichment/EnrichConfigForm';

function LabelsTab() {
  const { t } = useTranslation();
  const query = useAutoEnrichConfig();
  const save = useSaveAutoEnrichConfig();

  const [enabled, setEnabled] = useState(false);
  const [form, setForm] = useState<EnrichConfigValue>({
    vendors: [], promptSlug: '', models: {}, mergeModel: '',
  });

  useEffect(() => {
    if (!query.data) return;
    const { config, options } = query.data;
    setEnabled(config.enabled);
    setForm({
      vendors: config.vendors ?? [],
      promptSlug: config.prompt_slug ?? options.prompt_versions.find((p) => p.is_default)?.slug ?? '',
      models: (config.models as Record<string, string>) ?? {},
      mergeModel: config.merge_model ?? options.merge?.default_model ?? '',
    });
  }, [query.data]);

  if (query.isLoading) return <Skeleton height={240} />;
  if (query.isError || !query.data) return <Alert color="red">{String(query.error)}</Alert>;

  const promptVersion =
    query.data.options.prompt_versions.find((p) => p.slug === form.promptSlug)?.version ?? '';

  const submit = async () => {
    try {
      await save.mutateAsync({
        enabled,
        vendors: form.vendors as ('gemini' | 'openai' | 'tavily_deepseek')[],
        models: form.models,
        prompt_slug: form.promptSlug,
        prompt_version: promptVersion,
        merge_vendor: 'deepseek',
        merge_model: form.mergeModel,
      });
      notifications.show({ color: 'green', title: t('admin_auto_enrich.saved'), message: '' });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: t('admin_auto_enrich.save_error', {
          message: err instanceof Error ? err.message : 'unknown',
        }),
        message: '',
      });
    }
  };

  return (
    <Stack gap="md" mt="md">
      <Switch
        label={t('admin_auto_enrich.enabled_label')}
        checked={enabled}
        onChange={(e) => setEnabled(e.currentTarget.checked)}
      />
      <EnrichConfigForm options={query.data.options} value={form} onChange={setForm} />
      <Button
        onClick={submit}
        loading={save.isPending}
        disabled={enabled && form.vendors.length === 0}
      >
        {t('admin_auto_enrich.save')}
      </Button>
    </Stack>
  );
}

export function AdminAutoEnrichPage() {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Title order={3}>{t('admin_auto_enrich.title')}</Title>
      <Tabs defaultValue="labels">
        <Tabs.List>
          <Tabs.Tab value="labels">{t('admin_auto_enrich.tab_labels')}</Tabs.Tab>
          <Tabs.Tab value="artists" disabled>{t('admin_auto_enrich.tab_artists')}</Tabs.Tab>
          <Tabs.Tab value="tracks" disabled>{t('admin_auto_enrich.tab_tracks')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="labels">
          <LabelsTab />
        </Tabs.Panel>
        <Tabs.Panel value="artists">
          <Text c="dimmed" mt="md">{t('admin_auto_enrich.coming_soon')}</Text>
        </Tabs.Panel>
        <Tabs.Panel value="tracks">
          <Text c="dimmed" mt="md">{t('admin_auto_enrich.coming_soon')}</Text>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
