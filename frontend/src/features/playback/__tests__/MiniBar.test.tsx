import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../test/theme';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../i18n';
import type { ReactElement } from 'react';
import { MiniBar } from '../MiniBar';

function wrap(ui: ReactElement) {
  return (
    <MantineProvider theme={testTheme}>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter>{ui}</MemoryRouter>
      </I18nextProvider>
    </MantineProvider>
  );
}

const t = {
  id: 'A',
  title: 'T',
  artists: 'Ar',
  cover_url: null,
  duration_ms: 1000,
  spotify_id: 'spA',
};

describe('MiniBar', () => {
  it('renders nothing when track is null', () => {
    render(
      wrap(
        <MiniBar
          track={null}
          state="idle"
          sourceHref="/curate/s/b/u"
          onPlayPause={vi.fn()}
          onClose={vi.fn()}
        />,
      ),
    );
    expect(screen.queryByRole('region')).toBeNull();
    expect(screen.queryByRole('button', { name: /close/i })).toBeNull();
  });

  it('renders track title + play button + close button', () => {
    render(
      wrap(
        <MiniBar
          track={t}
          state="playing"
          sourceHref="/curate/s/b/u"
          onPlayPause={vi.fn()}
          onClose={vi.fn()}
        />,
      ),
    );
    expect(screen.getByText('T')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /close/i })).toBeInTheDocument();
  });

  it('clicking close fires onClose', async () => {
    const onClose = vi.fn();
    render(
      wrap(
        <MiniBar
          track={t}
          state="playing"
          sourceHref="/curate/s/b/u"
          onPlayPause={vi.fn()}
          onClose={onClose}
        />,
      ),
    );
    await userEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('clicking play/pause fires onPlayPause', async () => {
    const onPlayPause = vi.fn();
    render(
      wrap(
        <MiniBar
          track={t}
          state="playing"
          sourceHref="/curate/s/b/u"
          onPlayPause={onPlayPause}
          onClose={vi.fn()}
        />,
      ),
    );
    await userEvent.click(screen.getByRole('button', { name: /pause/i }));
    expect(onPlayPause).toHaveBeenCalled();
  });

  it('title links to sourceHref', () => {
    render(
      wrap(
        <MiniBar
          track={t}
          state="playing"
          sourceHref="/curate/s/b/u"
          onPlayPause={vi.fn()}
          onClose={vi.fn()}
        />,
      ),
    );
    const link = screen.getByRole('link', { name: /open in curate/i });
    expect(link.getAttribute('href')).toBe('/curate/s/b/u');
  });

  it('paused state shows Play icon', () => {
    render(
      wrap(
        <MiniBar
          track={t}
          state="paused"
          sourceHref="/curate/s/b/u"
          onPlayPause={vi.fn()}
          onClose={vi.fn()}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /^play$/i })).toBeInTheDocument();
  });

  it('renders deviceIndicator slot', () => {
    render(
      wrap(
        <MiniBar
          track={t}
          state="playing"
          sourceHref="/curate/s/b/u"
          onPlayPause={vi.fn()}
          onClose={vi.fn()}
          deviceIndicator={<span data-testid="indicator">x</span>}
        />,
      ),
    );
    expect(screen.getByTestId('indicator')).toBeInTheDocument();
  });
});
