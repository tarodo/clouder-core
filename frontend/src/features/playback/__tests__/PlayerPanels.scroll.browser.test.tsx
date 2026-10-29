import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import category from '../../categories/components/CategoryPlayerPanel.module.css';
import playlist from '../../playlists/components/PlaylistPlayerPanel.module.css';
import bucket from '../../triage/components/BucketPlayerPanel.module.css';

// The side player panels scroll on their own: at the end of the comments the wheel must not
// start scrolling the track list behind them (scroll chaining).
test.each([
  ['category', category.root],
  ['playlist', playlist.root],
  ['bucket', bucket.root],
])('the %s player panel keeps its scroll to itself', (_name, className) => {
  render(<div className={className} data-testid="panel" />);
  const style = getComputedStyle(screen.getByTestId('panel'));
  expect(style.overflowY).toBe('auto');
  expect(style.overscrollBehaviorY).toBe('contain');
});
