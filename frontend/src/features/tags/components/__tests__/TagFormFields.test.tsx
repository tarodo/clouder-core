import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { TagFormFields } from '../TagFormFields';

function W({ children }: { children: React.ReactNode }) {
  return <MantineProvider>{children}</MantineProvider>;
}

describe('TagFormFields', () => {
  it('shows inline error when name empty on submit', async () => {
    const onSubmit = vi.fn();
    render(
      <W>
        <TagFormFields
          mode="create"
          initialName=""
          initialColor={null}
          submitting={false}
          onCancel={() => {}}
          onSubmit={onSubmit}
        />
      </W>,
    );
    await userEvent.click(screen.getByRole('button', { name: /save|create/i }));
    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('emits trimmed name and selected colour', async () => {
    const onSubmit = vi.fn();
    render(
      <W>
        <TagFormFields
          mode="create"
          initialName=""
          initialColor={null}
          submitting={false}
          onCancel={() => {}}
          onSubmit={onSubmit}
        />
      </W>,
    );
    await userEvent.type(screen.getByRole('textbox', { name: /name/i }), '  Vocal  ');
    await userEvent.click(screen.getByRole('button', { name: /save|create/i }));
    expect(onSubmit).toHaveBeenCalledWith({ name: 'Vocal', color: null });
  });

  it('renders rename label when mode=rename', () => {
    render(
      <W>
        <TagFormFields
          mode="rename"
          initialName="Vocal"
          initialColor="#ff8800"
          submitting={false}
          onCancel={() => {}}
          onSubmit={() => {}}
        />
      </W>,
    );
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
  });

  it('shows server error from prop', () => {
    render(
      <W>
        <TagFormFields
          mode="create"
          initialName=""
          initialColor={null}
          submitting={false}
          serverError="Tag already exists"
          onCancel={() => {}}
          onSubmit={() => {}}
        />
      </W>,
    );
    expect(screen.getByText(/tag already exists/i)).toBeInTheDocument();
  });
});
