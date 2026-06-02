import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, Link } from 'react-router';
import { useBackOrFallback } from '../useBackOrFallback';

function Detail() {
  const goBack = useBackOrFallback('/fallback');
  return (
    <button type="button" onClick={goBack}>
      back
    </button>
  );
}

describe('useBackOrFallback', () => {
  it('goes back in history when an in-app entry exists', async () => {
    render(
      <MemoryRouter initialEntries={['/start']}>
        <Routes>
          <Route path="/start" element={<Link to="/detail">go</Link>} />
          <Route path="/detail" element={<Detail />} />
          <Route path="/fallback" element={<div>FALLBACK</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByText('go')); // /start -> /detail
    await userEvent.click(screen.getByText('back')); // back -> /start
    expect(screen.getByText('go')).toBeInTheDocument();
  });

  it('navigates to fallback when there is no history (deep-link)', async () => {
    render(
      <MemoryRouter initialEntries={['/detail']}>
        <Routes>
          <Route path="/detail" element={<Detail />} />
          <Route path="/fallback" element={<div>FALLBACK</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByText('back'));
    expect(screen.getByText('FALLBACK')).toBeInTheDocument();
  });
});
