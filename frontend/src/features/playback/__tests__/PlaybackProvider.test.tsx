import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { PlaybackProvider } from '../PlaybackProvider';
import { usePlayback } from '../usePlayback';

function Probe() {
  const playback = usePlayback();
  return (
    <div>
      <span data-testid="status">{playback.queue.status}</span>
      <span data-testid="cursor">{playback.queue.cursor}</span>
      <span data-testid="sdk-ready">{String(playback.sdk.ready)}</span>
    </div>
  );
}

describe('PlaybackProvider scaffold', () => {
  it('exposes idle queue + sdk.ready=false at mount', () => {
    render(
      <MantineProvider theme={testTheme}>
        <PlaybackProvider>
          <Probe />
        </PlaybackProvider>
      </MantineProvider>,
    );
    expect(screen.getByTestId('status').textContent).toBe('idle');
    expect(screen.getByTestId('cursor').textContent).toBe('0');
    expect(screen.getByTestId('sdk-ready').textContent).toBe('false');
  });

  it('throws if usePlayback called outside provider', () => {
    expect(() => render(<Probe />)).toThrow(/PlaybackProvider/);
  });
});
