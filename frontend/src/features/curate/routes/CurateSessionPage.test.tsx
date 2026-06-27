import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router';
import { telemetry } from '../../../lib/telemetry/sdk';
import { CurateSessionPage } from './CurateSessionPage';

vi.mock('../components/CurateSession', () => ({ CurateSession: () => <div>session</div> }));

describe('CurateSessionPage route telemetry', () => {
  beforeEach(() => vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true'));
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('sets the curate route pattern on mount, clears on unmount', () => {
    const setRoute = vi.spyOn(telemetry, 'setRoute');
    const { unmount } = render(
      <MemoryRouter initialEntries={['/curate/sty1/blk1/buck1']}>
        <Routes>
          <Route path="/curate/:styleId/:blockId/:bucketId" element={<CurateSessionPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(setRoute).toHaveBeenCalledWith('/curate/:styleId/:blockId/:bucketId');
    unmount();
    expect(setRoute).toHaveBeenLastCalledWith(null);
  });
});
