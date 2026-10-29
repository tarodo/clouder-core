import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import '../../../../i18n';
import { AiRepBadge, NamesWithAi, type AiRep } from '../AiRepBadge';

const rep = (level: AiRep['level']): AiRep => ({ level, ai: 80, checked: 87, total: 869 });
const wrap = (ui: React.ReactNode) => render(<MantineProvider>{ui}</MantineProvider>);

describe('AiRepBadge', () => {
  test('renders nothing without a level', () => {
    wrap(<AiRepBadge rep={null} />);
    expect(screen.queryByLabelText(/AI level/)).toBeNull();
  });

  test.each([1, 2, 3] as const)('names level %i', (level) => {
    wrap(<AiRepBadge rep={rep(level)} />);
    expect(screen.getByLabelText(`AI level ${level}`)).toHaveAttribute('data-level', String(level));
  });

  test('explains the counts on hover', async () => {
    wrap(<AiRepBadge rep={rep(3)} />);
    await userEvent.hover(screen.getByLabelText('AI level 3'));
    expect(await screen.findByText('AI: 80 of 87 checked · 869 in CLOUDER')).toBeInTheDocument();
  });
});

describe('NamesWithAi', () => {
  test('joins names and badges only the ones with a level', () => {
    wrap(
      <span data-testid="names">
        <NamesWithAi items={[{ name: 'Sus', ai: rep(1) }, { name: 'Clean', ai: null }]} />
      </span>,
    );
    expect(screen.getByTestId('names')).toHaveTextContent('SusAI, Clean');
    expect(screen.getAllByLabelText(/AI level/)).toHaveLength(1);
  });

  test('shows a dash when empty', () => {
    wrap(
      <span data-testid="names">
        <NamesWithAi items={[]} />
      </span>,
    );
    expect(screen.getByTestId('names')).toHaveTextContent('—');
  });
});
