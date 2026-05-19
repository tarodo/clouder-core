import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import i18n from '../../../../../i18n';
import { RunJsonViewer } from '../RunJsonViewer';

function wrap(ui: React.ReactNode) {
  return (
    <MantineProvider>
      <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>
    </MantineProvider>
  );
}

describe('RunJsonViewer', () => {
  it('renders pretty-printed JSON', () => {
    render(wrap(<RunJsonViewer data={{ a: 1 }} />));
    const pre = screen.getByText(/"a": 1/);
    expect(pre).toBeInTheDocument();
  });

  it('copies JSON to clipboard on button click', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(wrap(<RunJsonViewer data={{ a: 1 }} />));
    await userEvent.click(screen.getByText('Copy JSON'));
    expect(writeText).toHaveBeenCalledWith(JSON.stringify({ a: 1 }, null, 2));
  });
});
