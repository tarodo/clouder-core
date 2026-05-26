import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { EnrichConfigForm, type EnrichConfigValue } from '../EnrichConfigForm';
import type { EnrichmentOptions } from '../../../../../api/labels';

const options: EnrichmentOptions = {
  vendors: ['gemini', 'openai', 'tavily_deepseek'],
  prompt_versions: [{ slug: 'label_v3', version: 'v1', is_default: true }],
  default_models: { gemini: 'g', openai: 'o', tavily_deepseek: 'd' },
  merge: { vendor: 'deepseek', default_model: 'deepseek-v4-flash' },
};

function setup(value: EnrichConfigValue, onChange = vi.fn()) {
  render(
    <MantineProvider>
      <EnrichConfigForm options={options} value={value} onChange={onChange} />
    </MantineProvider>,
  );
  return onChange;
}

describe('EnrichConfigForm', () => {
  it('renders a checkbox per vendor', () => {
    setup({ vendors: [], promptSlug: '', models: {}, mergeModel: '' });
    expect(screen.getByLabelText('gemini')).toBeInTheDocument();
    expect(screen.getByLabelText('openai')).toBeInTheDocument();
  });

  it('emits onChange when a vendor is toggled', () => {
    const onChange = setup({ vendors: [], promptSlug: '', models: {}, mergeModel: '' });
    fireEvent.click(screen.getByLabelText('gemini'));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ vendors: ['gemini'] }),
    );
  });

  it('renders a model input only for selected vendors', () => {
    setup({ vendors: ['gemini'], promptSlug: 'label_v3', models: { gemini: 'g' }, mergeModel: 'm' });
    expect(screen.getByDisplayValue('g')).toBeInTheDocument();
  });
});
