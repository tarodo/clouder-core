import { describe, it, expect, beforeEach, vi } from 'vitest';
import { requireAuth, redirectIfAuthenticated } from '../requireAuth';
import { completeBootstrap, resetBootstrapForTests } from '../bootstrap';

const snapshotMock = vi.fn();
vi.mock('../AuthProvider', () => ({
  getAuthSnapshot: () => snapshotMock(),
  AuthContext: {},
}));

describe('requireAuth loader', () => {
  beforeEach(() => {
    resetBootstrapForTests();
    completeBootstrap();
  });

  it('returns null when authenticated', async () => {
    snapshotMock.mockReturnValue({ status: 'authenticated' });
    await expect(requireAuth({} as never)).resolves.toBeNull();
  });

  it('throws redirect to /login when unauthenticated', async () => {
    snapshotMock.mockReturnValue({ status: 'unauthenticated' });
    // react-router's `redirect` returns a real Response. Its `status` and
    // `headers` are prototype getters (not own properties), so vitest's
    // `toMatchObject` cannot see them — assert directly instead.
    let thrown: unknown;
    try {
      await requireAuth({} as never);
    } catch (e) {
      thrown = e;
    }
    expect(thrown).toBeInstanceOf(Response);
    const res = thrown as Response;
    expect(res.status).toBe(302);
    expect(typeof res.headers.get).toBe('function');
    expect(res.headers.get('Location')).toBe('/login');
  });
});

describe('redirectIfAuthenticated loader', () => {
  beforeEach(() => {
    resetBootstrapForTests();
    completeBootstrap();
  });

  it('returns null when unauthenticated', async () => {
    snapshotMock.mockReturnValue({ status: 'unauthenticated' });
    await expect(redirectIfAuthenticated({} as never)).resolves.toBeNull();
  });

  it('throws redirect to / when authenticated', async () => {
    snapshotMock.mockReturnValue({ status: 'authenticated' });
    // See comment above on requireAuth: Response uses prototype getters.
    let thrown: unknown;
    try {
      await redirectIfAuthenticated({} as never);
    } catch (e) {
      thrown = e;
    }
    expect(thrown).toBeInstanceOf(Response);
    const res = thrown as Response;
    expect(res.status).toBe(302);
    expect(res.headers.get('Location')).toBe('/');
  });
});
