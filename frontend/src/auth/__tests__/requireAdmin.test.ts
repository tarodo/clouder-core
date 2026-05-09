import { describe, expect, it, vi } from 'vitest';
import { requireAdmin } from '../requireAdmin';

vi.mock('../bootstrap', () => ({
  bootstrapPromise: () => Promise.resolve(),
}));

const snapMock = vi.hoisted(() => vi.fn());
vi.mock('../AuthProvider', () => ({
  getAuthSnapshot: () => snapMock(),
}));

describe('requireAdmin', () => {
  it('redirects to / when unauthenticated', async () => {
    snapMock.mockReturnValue({ status: 'unauthenticated' });
    await expect(
      requireAdmin({ request: new Request('http://x/admin'), params: {} } as never),
    ).rejects.toMatchObject({ status: 302 });
  });

  it('redirects to / when user has is_admin=false', async () => {
    snapMock.mockReturnValue({
      status: 'authenticated',
      user: { id: 'u', spotify_id: 's', display_name: 'D', is_admin: false },
      expiresAt: 0,
      spotifyAccessToken: null,
    });
    await expect(
      requireAdmin({ request: new Request('http://x/admin'), params: {} } as never),
    ).rejects.toMatchObject({ status: 302 });
  });

  it('returns null when admin', async () => {
    snapMock.mockReturnValue({
      status: 'authenticated',
      user: { id: 'u', spotify_id: 's', display_name: 'D', is_admin: true },
      expiresAt: 0,
      spotifyAccessToken: null,
    });
    const result = await requireAdmin({
      request: new Request('http://x/admin'),
      params: {},
    } as never);
    expect(result).toBeNull();
  });
});
