import type { ReactNode } from 'react';
import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import '../../../../i18n';
import { clouderTheme } from '../../../../theme';
import { BucketDistributeButtons } from '../BucketDistributeButtons';
import { DestinationGrid } from '../../../curate/components/DestinationGrid';
import type { TriageBucket } from '../../lib/bucketLabels';

const stage = (id: string, name: string): TriageBucket => ({
  id, bucket_type: 'STAGING', category_id: `c-${id}`, category_name: name, inactive: false, track_count: 0,
});
const discard: TriageBucket = { id: 'disc', bucket_type: 'DISCARD', inactive: false, track_count: 0 };
const buckets = [stage('s1', 'Warm-up'), stage('s2', 'Peak time'), stage('s3', 'Closing'), discard];

/** sRGBA of any CSS colour (Chromium keeps oklch() in computed styles). */
function rgba(color: string): [number, number, number, number] {
  const ctx = document.createElement('canvas').getContext('2d')!;
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 1, 1);
  const [r = 0, g = 0, b = 0, a = 0] = ctx.getImageData(0, 0, 1, 1).data;
  return [r, g, b, a];
}
const isRed = (color: string) => {
  const [r, g, b] = rgba(color);
  return r > 150 && r - g > 60 && r - b > 60;
};
const style = (name: string) => getComputedStyle(screen.getByRole('button', { name }));
const bg = (name: string) => style(name).backgroundColor;
/** The secondary must read as lit, not fainter than an unlit button. */
const hasDarkBorder = (name: string) => {
  const [r, g, b, a] = rgba(style(name).borderTopColor);
  return a > 200 && Math.max(r, g, b) < 80;
};

/** Lit DISCARD: tinted (not solid danger, not the unlit pale fill) with a danger border. */
function expectSoftDiscard(lit: string, unlit: string) {
  const solid = rgba(getComputedStyle(document.documentElement).getPropertyValue('--color-danger'));
  const bgLit = bg(lit);
  expect(bgLit).not.toBe(unlit);
  expect(rgba(bgLit)).not.toEqual(solid);
  expect(rgba(style(lit).borderTopColor)).toEqual(solid);
  expect(style(lit).borderTopWidth).toBe('1px');
}

const wrap = (ui: ReactNode) => render(<MantineProvider theme={clouderTheme}>{ui}</MantineProvider>);

describe('suggested buttons, real styles', () => {
  test('bucket player: filled primary, pale non-red secondary, soft red DISCARD primary', () => {
    wrap(
      <>
        <BucketDistributeButtons destinations={buckets} suggested={{ primary: 's2', secondary: 's1' }}
          onDistribute={() => {}} />
        <BucketDistributeButtons destinations={[discard]} suggested={{ primary: 'disc', secondary: null }}
          onDistribute={() => {}} />
      </>,
    );
    const primary = bg('Peak time, suggested');
    const secondary = bg('Warm-up, weaker suggestion');
    const unlit = bg('Closing');
    expect(new Set([primary, secondary, unlit]).size).toBe(3);
    expect(isRed(secondary)).toBe(false);
    expect(hasDarkBorder('Warm-up, weaker suggestion')).toBe(true);
    expect(hasDarkBorder('Closing')).toBe(false);
    expectSoftDiscard('DISCARD, suggested', bg('DISCARD'));
  });

  test('curate: filled primary, pale non-red secondary, soft red DISCARD primary', () => {
    wrap(
      <>
        <DestinationGrid buckets={buckets} currentBucketId="new" lastTappedBucketId={null} forceMode={false}
          suggested={{ primary: 's2', secondary: 's1' }} onAssign={() => {}} onToggleForce={() => {}} />
        <DestinationGrid buckets={[discard]} currentBucketId="new" lastTappedBucketId={null} forceMode={false}
          suggested={{ primary: 'disc', secondary: null }} onAssign={() => {}} onToggleForce={() => {}} />
      </>,
    );
    const primary = bg('Assign to Peak time, suggested');
    const secondary = bg('Assign to Warm-up, weaker suggestion');
    const unlit = bg('Assign to Closing');
    expect(new Set([primary, secondary, unlit]).size).toBe(3);
    expect(isRed(secondary)).toBe(false);
    expect(hasDarkBorder('Assign to Warm-up, weaker suggestion')).toBe(true);
    expect(hasDarkBorder('Assign to Closing')).toBe(false);
    expectSoftDiscard('Assign to DISCARD, suggested', bg('Assign to DISCARD'));
  });

  test('unsure: the category and DISCARD both pale, nothing filled or soft red', () => {
    const unsure = { primary: 's2', secondary: 'disc', unsure: true };
    wrap(
      <>
        <BucketDistributeButtons destinations={buckets} suggested={unsure} onDistribute={() => {}} />
        <DestinationGrid buckets={buckets} currentBucketId="new" lastTappedBucketId={null} forceMode={false}
          suggested={unsure} onAssign={() => {}} onToggleForce={() => {}} />
      </>,
    );
    for (const name of [
      'Peak time, weaker suggestion',
      'DISCARD, weaker suggestion',
      'Assign to Peak time, weaker suggestion',
      'Assign to DISCARD, weaker suggestion',
    ]) {
      expect(hasDarkBorder(name)).toBe(true);
    }
    expect(screen.queryByRole('button', { name: /, suggested$/ })).toBeNull();
    expect(bg('Assign to DISCARD, weaker suggestion')).toBe(bg('Assign to Peak time, weaker suggestion'));
  });
});
