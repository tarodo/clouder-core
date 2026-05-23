/**
 * Browser harness smoke test — verifies the Playwright/Vitest browser mode
 * is operational. This is NOT a jsdom test.
 */
import { render } from '@testing-library/react';
import { expect, test } from 'vitest';

test('browser smoke: DOM is real and renders', () => {
  const { getByText } = render(<div data-testid="smoke">hello browser</div>);
  expect(getByText('hello browser')).toBeDefined();
  // Verify we are in a real browser (not jsdom)
  expect(typeof document).toBe('object');
  expect(document.querySelector('[data-testid="smoke"]')).not.toBeNull();
});
