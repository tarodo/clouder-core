import { useEffect, useState } from 'react';
import { Tabs, Stack, Switch, Button, Alert, Text } from '@mantine/core';
import { PageHeader } from '../../../components/PageHeader';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useAutoEnrichConfig } from '../hooks/useAutoEnrichConfig';
import { useSaveAutoEnrichConfig } from '../hooks/useSaveAutoEnrichConfig';
import { useArtistAutoEnrichConfig } from '../hooks/useArtistAutoEnrichConfig';
import { useSaveArtistAutoEnrichConfig } from '../hooks/useSaveArtistAutoEnrichConfig';
import { EnrichConfigForm, type EnrichConfigValue } from '../components/enrichment/EnrichConfigForm';
import { Ghost, GhostScope, useRemembered } from '../../../components/Ghost';
import type { EnrichmentOptions } from '../../../api/labels';

/** A tab's settings: the switch, the vendor form and Save. */
function ConfigBody(props: {
  options: EnrichmentOptions;
  enabled: boolean;
  onEnabled: (next: boolean) => void;
  form: EnrichConfigValue;
  onForm: (next: EnrichConfigValue) => void;
  onSave: () => void;
  saving: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Stack gap="md" mt="md">
      <Ghost>
        <Switch
          label={t('admin_auto_enrich.enabled_label')}
          checked={props.enabled}
          onChange={(e) => props.onEnabled(e.currentTarget.checked)}
        />
      </Ghost>
      <EnrichConfigForm options={props.options} value={props.form} onChange={props.onForm} />
      <Ghost block>
        <Button
          onClick={props.onSave}
          loading={props.saving}
          disabled={props.enabled && props.form.vendors.length === 0}
        >
          {t('admin_auto_enrich.save')}
        </Button>
      </Ghost>
    </Stack>
  );
}

const VENDORS = ['gemini', 'openai', 'tavily_deepseek'];
const noop = () => {};

/** A tab's ghost while its config loads: as many vendors (and picked ones) as last time. */
function ConfigGhost({ vendors, picked }: { vendors: number; picked: number }) {
  const options = {
    vendors: VENDORS.slice(0, vendors),
    prompt_versions: [{ slug: 'placeholder', version: 'v1', is_default: true }],
    default_models: {},
    merge: { vendor: 'deepseek', default_model: 'placeholder' },
  } as EnrichmentOptions;
  const form = {
    vendors: VENDORS.slice(0, Math.min(picked, vendors)),
    promptSlug: 'placeholder',
    models: {},
    mergeModel: 'placeholder',
  };
  return (
    <GhostScope on>
      <ConfigBody
        options={options}
        enabled
        onEnabled={noop}
        form={form}
        onForm={noop}
        onSave={noop}
        saving={false}
      />
    </GhostScope>
  );
}

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

  const vendors = useRemembered(
    'admin.auto_enrich.labels.vendors',
    query.data?.options.vendors.length,
    3,
  );
  const picked = useRemembered(
    'admin.auto_enrich.labels.picked',
    query.data && (query.data.config.vendors ?? []).length,
    1,
  );
  if (query.isLoading) return <ConfigGhost vendors={vendors} picked={picked} />;
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
    <ConfigBody
      options={query.data.options}
      enabled={enabled}
      onEnabled={setEnabled}
      form={form}
      onForm={setForm}
      onSave={submit}
      saving={save.isPending}
    />
  );
}

function ArtistsTab() {
  const { t } = useTranslation();
  const query = useArtistAutoEnrichConfig();
  const save = useSaveArtistAutoEnrichConfig();

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

  const vendors = useRemembered(
    'admin.auto_enrich.artists.vendors',
    query.data?.options.vendors.length,
    3,
  );
  const picked = useRemembered(
    'admin.auto_enrich.artists.picked',
    query.data && (query.data.config.vendors ?? []).length,
    1,
  );
  if (query.isLoading) return <ConfigGhost vendors={vendors} picked={picked} />;
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
    <ConfigBody
      options={query.data.options}
      enabled={enabled}
      onEnabled={setEnabled}
      form={form}
      onForm={setForm}
      onSave={submit}
      saving={save.isPending}
    />
  );
}

export function AdminAutoEnrichPage() {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <PageHeader title={t('admin_auto_enrich.title')} subtitle={t('admin_auto_enrich.subtitle')}>
        <Tabs defaultValue="labels">
          <Tabs.List>
            <Tabs.Tab value="labels">{t('admin_auto_enrich.tab_labels')}</Tabs.Tab>
            <Tabs.Tab value="artists">{t('admin_auto_enrich.tab_artists')}</Tabs.Tab>
            <Tabs.Tab value="tracks" disabled>{t('admin_auto_enrich.tab_tracks')}</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="labels">
            <LabelsTab />
          </Tabs.Panel>
          <Tabs.Panel value="artists">
            <ArtistsTab />
          </Tabs.Panel>
          <Tabs.Panel value="tracks">
            <Text c="dimmed" mt="md">{t('admin_auto_enrich.coming_soon')}</Text>
          </Tabs.Panel>
        </Tabs>
      </PageHeader>
    </Stack>
  );
}
