import { describe, it, expect } from 'vitest';
import { clouderTheme } from '../theme';

describe('clouderTheme', () => {
  it('disables the focus ring app-wide', () => {
    expect(clouderTheme.focusRing).toBe('never');
  });
});
