import { Stack, Title, Checkbox, Select, TextInput, Group, Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { EnrichmentOptions } from '../../../../api/labels';
import { Ghost } from '../../../../components/Ghost';

export interface EnrichConfigValue {
  vendors: string[];
  promptSlug: string;
  models: Record<string, string>;
  mergeModel: string;
}

interface Props {
  options: EnrichmentOptions;
  value: EnrichConfigValue;
  onChange: (next: EnrichConfigValue) => void;
}

export function EnrichConfigForm({ options, value, onChange }: Props) {
  const { t } = useTranslation();
  const set = (patch: Partial<EnrichConfigValue>) => onChange({ ...value, ...patch });

  return (
    <Stack gap="md">
      <Stack gap="xs">
        <Title order={6}>{t('admin_enrichment.enqueue_drawer.vendors_label')}</Title>
        {options.vendors.map((v) => (
          <Ghost key={v}>
            <Checkbox
              label={v}
              checked={value.vendors.includes(v)}
              onChange={(e) =>
                set({
                  vendors: e.currentTarget.checked
                    ? [...value.vendors, v]
                    : value.vendors.filter((x) => x !== v),
                })
              }
            />
          </Ghost>
        ))}
      </Stack>
      <Ghost block>
        <Select
          label={t('admin_enrichment.enqueue_drawer.prompt_label')}
          value={value.promptSlug}
          data={options.prompt_versions.map((p) => ({
            value: p.slug ?? '',
            label: `${p.slug}@${p.version}`,
          }))}
          onChange={(v) => v && set({ promptSlug: v })}
        />
      </Ghost>
      <Stack gap="xs">
        <Title order={6}>{t('admin_enrichment.enqueue_drawer.models_label')}</Title>
        {value.vendors.map((v) => (
          <Ghost key={v} block>
            <TextInput
              label={v}
              value={value.models[v] ?? ''}
              onChange={(e) => set({ models: { ...value.models, [v]: e.currentTarget.value } })}
            />
          </Ghost>
        ))}
      </Stack>
      <Group gap="xs" align="end">
        <Stack gap={4}>
          <Title order={6}>{t('admin_enrichment.enqueue_drawer.merge_vendor_label')}</Title>
          <Ghost>
            <Badge>deepseek</Badge>
          </Ghost>
        </Stack>
        <Ghost grow>
          <TextInput
            label={t('admin_enrichment.enqueue_drawer.merge_model_label')}
            value={value.mergeModel}
            onChange={(e) => set({ mergeModel: e.currentTarget.value })}
            style={{ flex: 1 }}
          />
        </Ghost>
      </Group>
    </Stack>
  );
}
