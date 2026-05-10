// frontend/src/features/curate/components/__tests__/HotkeyOverlay.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { HotkeyOverlay } from '../HotkeyOverlay';

vi.mock('@mantine/hooks', async () => {
  const actual = await vi.importActual<typeof import('@mantine/hooks')>('@mantine/hooks');
  return { ...actual, useMediaQuery: vi.fn(() => false) };
});

const wrap = (ui: React.ReactElement) => (
  <MantineProvider theme={testTheme}>{ui}</MantineProvider>
);

describe('HotkeyOverlay', () => {
  it('does not render when opened=false', () => {
    render(
      wrap(<HotkeyOverlay opened={false} onClose={() => {}} hasOverflow={false} />),
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders all key sections on desktop when opened', async () => {
    render(
      wrap(<HotkeyOverlay opened={true} onClose={() => {}} hasOverflow={false} />),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Keyboard shortcuts/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Assign to staging category 1–9/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Skip without assigning/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Show \/ hide this overlay/i)).toBeInTheDocument();
  });

  it('shows playback hotkey rows in desktop mode', async () => {
    const mod = await import('@mantine/hooks');
    (mod.useMediaQuery as unknown as ReturnType<typeof vi.fn>).mockReturnValue(false);
    render(
      wrap(<HotkeyOverlay opened={true} onClose={() => {}} hasOverflow={false} />),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/^Playback$/)).toBeInTheDocument();
    expect(within(dialog).getByText('Play / pause')).toBeInTheDocument();
    expect(within(dialog).getByText('Previous track')).toBeInTheDocument();
    expect(within(dialog).getByText('Next track')).toBeInTheDocument();
    expect(within(dialog).getByText('Seek −10s')).toBeInTheDocument();
    expect(within(dialog).getByText('Seek +10s')).toBeInTheDocument();
    expect(within(dialog).getByText('Seek 0%')).toBeInTheDocument();
    expect(within(dialog).getByText('Seek 20%')).toBeInTheDocument();
    expect(within(dialog).getByText('Seek 40%')).toBeInTheDocument();
    expect(within(dialog).getByText('Seek 60%')).toBeInTheDocument();
    expect(within(dialog).getByText('Seek 80%')).toBeInTheDocument();
  });

  it('shows overflow note when hasOverflow=true', async () => {
    render(
      wrap(<HotkeyOverlay opened={true} onClose={() => {}} hasOverflow={true} />),
    );
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByText(/Categories beyond 9 are accessible via the More/i),
    ).toBeInTheDocument();
  });

  it('always shows audio playback footer note', async () => {
    render(
      wrap(<HotkeyOverlay opened={true} onClose={() => {}} hasOverflow={false} />),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Audio playback/i)).toBeInTheDocument();
  });

  it('mobile copy when useMediaQuery returns true', async () => {
    const mod = await import('@mantine/hooks');
    (mod.useMediaQuery as unknown as ReturnType<typeof vi.fn>).mockReturnValue(true);
    render(
      wrap(<HotkeyOverlay opened={true} onClose={() => {}} hasOverflow={false} />),
    );
    const dialog = await screen.findByRole('dialog');
    expect(
      within(dialog).getByText(/Keyboard shortcuts available on desktop only/i),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(/Assign to staging category 1–9/i)).toBeNull();
    expect(within(dialog).queryByText(/^Playback$/)).toBeNull();
    expect(within(dialog).queryByText(/Play \/ pause/i)).toBeNull();
  });

  it('close button fires onClose', async () => {
    const onClose = vi.fn();
    render(wrap(<HotkeyOverlay opened={true} onClose={onClose} hasOverflow={false} />));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders the L hotkey row for Toggle Force mode in desktop layout', async () => {
    render(
      wrap(<HotkeyOverlay opened={true} onClose={() => {}} hasOverflow={false} />),
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Toggle Force mode')).toBeInTheDocument();
    expect(within(dialog).getByText('L')).toBeInTheDocument();
  });
});
