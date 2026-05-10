import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
import { testTheme } from '../../../../test/theme';
import { ForceToggle } from '../ForceToggle';

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <I18nextProvider i18n={i18n}>
      <MantineProvider theme={testTheme}>{ui}</MantineProvider>
    </I18nextProvider>,
  );
}

describe('ForceToggle', () => {
  it('renders label "Force" and hotkey hint "L" on desktop (compact=false)', () => {
    renderWithProviders(
      <ForceToggle active={false} hotkeyHint="L" compact={false} onClick={() => {}} />,
    );
    expect(screen.getByText('Force')).toBeInTheDocument();
    expect(screen.getByText('L')).toBeInTheDocument();
  });

  it('hides text label when compact=true (icon + L only)', () => {
    renderWithProviders(
      <ForceToggle active={false} hotkeyHint="L" compact={true} onClick={() => {}} />,
    );
    expect(screen.queryByText('Force')).not.toBeInTheDocument();
    expect(screen.getByText('L')).toBeInTheDocument();
  });

  it('renders aria-pressed=false when active=false', () => {
    renderWithProviders(
      <ForceToggle active={false} hotkeyHint="L" compact={false} onClick={() => {}} />,
    );
    const btn = screen.getByRole('button');
    expect(btn).toHaveAttribute('aria-pressed', 'false');
    expect(btn).toHaveAttribute('aria-label', 'Force mode off');
  });

  it('renders aria-pressed=true when active=true', () => {
    renderWithProviders(
      <ForceToggle active={true} hotkeyHint="L" compact={false} onClick={() => {}} />,
    );
    const btn = screen.getByRole('button');
    expect(btn).toHaveAttribute('aria-pressed', 'true');
    expect(btn).toHaveAttribute('aria-label', 'Force mode on');
  });

  it('calls onClick once when clicked', () => {
    const onClick = vi.fn();
    renderWithProviders(
      <ForceToggle active={false} hotkeyHint="L" compact={false} onClick={onClick} />,
    );
    fireEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('omits hotkey hint element when hotkeyHint is null', () => {
    renderWithProviders(
      <ForceToggle active={false} hotkeyHint={null} compact={true} onClick={() => {}} />,
    );
    expect(screen.queryByText('L')).not.toBeInTheDocument();
  });
});
