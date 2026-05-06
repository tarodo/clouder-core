import { spotifyTokenStore } from '../../../auth/spotifyTokenStore';
import type { SpotifyDevice } from '../lib/deviceTypes';

const BASE = 'https://api.spotify.com';

interface CallOptions {
  onAuthExpired?: () => Promise<boolean>;
}

interface PlayArgs {
  uris: string[];
  deviceId: string;
}

interface TransferArgs {
  deviceId: string;
  play: boolean;
}

interface SeekArgs {
  positionMs: number;
  deviceId: string;
}

async function call(
  method: 'PUT' | 'POST' | 'GET',
  path: string,
  body: unknown | null,
  opts: CallOptions,
): Promise<Response> {
  const token = spotifyTokenStore.get();
  if (!token) throw new Error('spotify_token_missing');

  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: 'application/json',
  };
  if (body != null) headers['Content-Type'] = 'application/json';

  const init: RequestInit = {
    method,
    headers,
    body: body != null ? JSON.stringify(body) : undefined,
  };
  const url = `${BASE}${path}`;

  const res = await fetch(url, init);
  if (res.status !== 401) return ensureOk(res);

  const refreshed = opts.onAuthExpired ? await opts.onAuthExpired() : false;
  if (!refreshed) return ensureOk(res);

  const retryToken = spotifyTokenStore.get();
  if (!retryToken) return ensureOk(res);
  const retry = await fetch(url, {
    ...init,
    headers: { ...headers, Authorization: `Bearer ${retryToken}` },
  });
  return ensureOk(retry);
}

async function ensureOk(res: Response): Promise<Response> {
  if (res.ok || res.status === 204) return res;
  throw new Error(`spotify_api_${res.status}`);
}

export const spotifyApi = {
  async play(args: PlayArgs, opts: CallOptions = {}): Promise<void> {
    const path = `/v1/me/player/play?device_id=${encodeURIComponent(args.deviceId)}`;
    await call('PUT', path, { uris: args.uris }, opts);
  },
  async transferMyPlayback(args: TransferArgs, opts: CallOptions = {}): Promise<void> {
    await call('PUT', '/v1/me/player', { device_ids: [args.deviceId], play: args.play }, opts);
  },
  async seek(args: SeekArgs, opts: CallOptions = {}): Promise<void> {
    const path = `/v1/me/player/seek?position_ms=${args.positionMs}&device_id=${encodeURIComponent(args.deviceId)}`;
    await call('PUT', path, null, opts);
  },
  async getMyDevices(opts: CallOptions = {}): Promise<SpotifyDevice[]> {
    const res = await call('GET', '/v1/me/player/devices', null, opts);
    const json = (await res.json()) as { devices?: SpotifyDevice[] };
    return json.devices ?? [];
  },
};
