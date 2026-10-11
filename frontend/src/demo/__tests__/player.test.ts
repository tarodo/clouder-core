import { describe, expect, it, vi } from 'vitest';
import { DEMO_DEVICE_ID, DemoPlayer, demoSpotifyApi, type AudioLike } from '../player';

class FakeAudio implements AudioLike {
  src = '';
  currentTime = 0;
  duration = Number.NaN;
  paused = true;
  ended = false;
  volume = 1;
  preload = '';
  private readonly listeners = new Map<string, (() => void)[]>();
  addEventListener(type: string, cb: () => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), cb]);
  }
  fire(type: string): void {
    for (const cb of this.listeners.get(type) ?? []) cb();
  }
  play = vi.fn(async () => {
    this.paused = false;
    this.ended = false;
    this.duration = 150;
    this.fire('play');
  });
  pause = vi.fn(() => {
    this.paused = true;
    this.fire('pause');
  });
}

interface State {
  paused: boolean;
  position: number;
  duration: number;
  track_window: { current_track: { uri: string } };
}

const CLIPS: Record<string, string> = {
  sp1: '/clouder-core/demo/audio/melodic-1.mp3',
  sp2: '/clouder-core/demo/audio/melodic-2.mp3',
};

function setup(load = vi.fn(async (url: string) => `blob:${url}`)) {
  const audio = new FakeAudio();
  const player = new DemoPlayer((id) => CLIPS[id] ?? null, audio, load);
  const states: State[] = [];
  player.addListener('player_state_changed', (s) => states.push(s as State));
  const api = demoSpotifyApi(player);
  return { audio, player, states, api, load, last: () => states[states.length - 1] };
}

describe('DemoPlayer', () => {
  it('announces one ready device on connect', async () => {
    const { player } = setup();
    const ready = vi.fn();
    player.addListener('ready', ready);
    await player.connect();
    await Promise.resolve();
    expect(ready).toHaveBeenCalledWith({ device_id: DEMO_DEVICE_ID });
  });

  it('plays a track by its Spotify URI from its preview clip', async () => {
    const { audio, api, last } = setup();
    const res = await api('PUT', `/v1/me/player/play?device_id=${DEMO_DEVICE_ID}`, {
      uris: ['spotify:track:sp1'],
    });
    expect(res.status).toBe(204);
    // Played from a blob: media fetched through a service worker cannot be seeked.
    expect(audio.src).toBe('blob:/clouder-core/demo/audio/melodic-1.mp3');
    expect(audio.play).toHaveBeenCalled();
    expect(last()).toMatchObject({
      paused: false,
      duration: 150_000,
      track_window: { current_track: { uri: 'spotify:track:sp1' } },
    });
  });

  it('pauses, toggles and seeks through the audio element', async () => {
    const { audio, player, api, last } = setup();
    await api('PUT', '/v1/me/player/play', { uris: ['spotify:track:sp1'] });
    await player.togglePlay();
    expect(audio.paused).toBe(true);
    await player.togglePlay();
    expect(audio.paused).toBe(false);
    await player.seek(60_000);
    expect(audio.currentTime).toBe(60);
    expect(last()?.position).toBe(60_000);
    await api('PUT', '/v1/me/player/pause', null);
    expect(audio.paused).toBe(true);
    await api('PUT', '/v1/me/player/seek?position_ms=30000', null);
    expect(audio.currentTime).toBe(30);
  });

  it('downloads each clip once', async () => {
    const { api, load } = setup();
    await api('PUT', '/v1/me/player/play', { uris: ['spotify:track:sp1'] });
    await api('PUT', '/v1/me/player/play', { uris: ['spotify:track:sp1'] });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('plays the last track asked for when downloads finish out of order', async () => {
    let release: (v: string) => void = () => {};
    const load = vi.fn((url: string) =>
      url.endsWith('melodic-1.mp3')
        ? new Promise<string>((r) => (release = r))
        : Promise.resolve(`blob:${url}`),
    );
    const { audio, api } = setup(load);
    const first = api('PUT', '/v1/me/player/play', { uris: ['spotify:track:sp1'] });
    await api('PUT', '/v1/me/player/play', { uris: ['spotify:track:sp2'] });
    release('blob:/clouder-core/demo/audio/melodic-1.mp3');
    await first;
    expect(audio.src).toBe('blob:/clouder-core/demo/audio/melodic-2.mp3');
  });

  it('stays paused after a failed download and tries again next time', async () => {
    const load = vi
      .fn<(url: string) => Promise<string>>()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue('blob:/clouder-core/demo/audio/melodic-1.mp3');
    const { audio, api } = setup(load);
    const failed = await api('PUT', '/v1/me/player/play', { uris: ['spotify:track:sp1'] });
    expect(failed.status).toBe(204);
    expect(audio.paused).toBe(true);
    await api('PUT', '/v1/me/player/play', { uris: ['spotify:track:sp1'] });
    expect(load).toHaveBeenCalledTimes(2);
    expect(audio.paused).toBe(false);
  });

  it('reports the end of a clip as paused at zero, so the queue moves on', async () => {
    const { audio, api, last } = setup();
    await api('PUT', '/v1/me/player/play', { uris: ['spotify:track:sp1'] });
    audio.currentTime = 150;
    audio.paused = true;
    audio.ended = true;
    audio.fire('ended');
    expect(last()).toMatchObject({ paused: true, position: 0 });
  });

  it('stays paused when the browser blocks autoplay', async () => {
    const { audio, api, last } = setup();
    audio.play.mockRejectedValueOnce(new DOMException('blocked', 'NotAllowedError'));
    const res = await api('PUT', '/v1/me/player/play', { uris: ['spotify:track:sp1'] });
    expect(res.status).toBe(204);
    expect(last()?.paused).toBe(true);
  });

  it('answers the Web API: one device, no cover, 404 for a track it has no clip for', async () => {
    const { api } = setup();
    const devices = await (await api('GET', '/v1/me/player/devices', null)).json();
    expect(devices.devices).toEqual([
      expect.objectContaining({ id: DEMO_DEVICE_ID, is_active: true }),
    ]);
    expect(await (await api('GET', '/v1/tracks/sp1', null)).json()).toEqual({});
    expect((await api('PUT', '/v1/me/player/play', { uris: ['spotify:track:nope'] })).status).toBe(
      404,
    );
    expect(
      (await api('PUT', '/v1/me/player', { device_ids: [DEMO_DEVICE_ID], play: false })).status,
    ).toBe(204);
  });
});
