import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import '../../../../i18n';
import { clouderTheme } from '../../../../theme';
import { AiRepBadge } from '../AiRepBadge';

const WHITE = 'rgb(255, 255, 255)';
const BLACK = 'rgb(0, 0, 0)';
const GREY = 'rgb(107, 107, 107)';

describe('AiRepBadge, real styles', () => {
  test.each([
    [1, WHITE, BLACK, BLACK],
    [2, GREY, WHITE, GREY],
    [3, BLACK, WHITE, BLACK],
  ] as const)('level %i: fill, text and border', (level, bg, fg, border) => {
    render(
      <MantineProvider theme={clouderTheme}>
        <AiRepBadge rep={{ level, ai: 1, checked: 2, total: 3 }} />
      </MantineProvider>,
    );
    const style = getComputedStyle(screen.getByLabelText(`AI level ${level}`));
    expect([style.backgroundColor, style.color, style.borderTopColor]).toEqual([bg, fg, border]);
    expect(style.borderTopWidth).toBe('1px');
  });
});
