import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import '../../../../i18n';
import { clouderTheme } from '../../../../theme';
import { BucketBadge } from '../BucketBadge';

const bucket = (bucket_type: 'NEW' | 'STAGING', category_name: string | null = null) => ({
  id: bucket_type, bucket_type, track_count: 1, inactive: false,
  category_id: category_name ? 'c1' : null, category_name,
});

describe('BucketBadge typography', () => {
  // Mantine's `ff` takes 'monospace' | 'text' | a font stack; 'mono' / 'sans' became a
  // literal `font-family: mono` and the browser fell back to a serif face.
  test('technical codes use the mono stack, category names the sans stack', async () => {
    render(
      <MantineProvider theme={clouderTheme}>
        <BucketBadge bucket={bucket('NEW')} />
        <BucketBadge bucket={bucket('STAGING', 'Peak time')} />
      </MantineProvider>,
    );
    const family = (text: string) => getComputedStyle(screen.getByText(text)).fontFamily;
    expect(family('NEW')).toContain('Geist Mono');
    expect(family('Peak time')).toContain('Geist');
    expect(family('Peak time')).not.toContain('Geist Mono');
  });
});
