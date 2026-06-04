import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { PageHeader } from '../PageHeader';

function renderHeader() {
  return render(
    <MantineProvider>
      <div style={{ width: 800 }}>
        <PageHeader
          title="Labels"
          actions={<button>Add</button>}
          subtitle="All labels in this style"
        />
      </div>
    </MantineProvider>,
  );
}

describe('PageHeader layout', () => {
  test('actions sit to the right of the title', () => {
    renderHeader();
    const title = screen.getByRole('heading', { level: 2, name: 'Labels' }).getBoundingClientRect();
    const action = screen.getByRole('button', { name: 'Add' }).getBoundingClientRect();
    expect(action.left).toBeGreaterThan(title.right);
  });

  test('subtitle sits below the title row', () => {
    renderHeader();
    const title = screen.getByRole('heading', { level: 2, name: 'Labels' }).getBoundingClientRect();
    const subtitle = screen.getByText('All labels in this style').getBoundingClientRect();
    expect(subtitle.top).toBeGreaterThan(title.bottom - 1);
  });
});
