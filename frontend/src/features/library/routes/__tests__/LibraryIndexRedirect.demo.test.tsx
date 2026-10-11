import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router';
import { LibraryIndexRedirect } from '../LibraryIndexRedirect';

vi.mock('../../../../demo/mode', () => ({ isDemo: () => true }));

function Style() {
  return <p>{useParams().styleId}</p>;
}

describe('LibraryIndexRedirect in the demo', () => {
  it('opens a style the sample catalog has', () => {
    render(
      <MemoryRouter initialEntries={['/library']}>
        <Routes>
          <Route path="/library" element={<LibraryIndexRedirect />} />
          <Route path="/library/:styleId" element={<Style />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('tech-house')).toBeTruthy();
  });
});
