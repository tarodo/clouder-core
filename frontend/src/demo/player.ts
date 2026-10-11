/**
 * Demo playback: stands in for the Spotify Web Playback SDK player and for the Web API
 * calls the app makes, with one <audio> element and the demo's eight tracks (`clips.ts`).
 * PlaybackProvider and every player UI (buttons, scrub bar, hotkeys, queue, device picker)
 * run unchanged on top of it.
 */
import type { SpotifyDevice } from '../features/playback/lib/deviceTypes';

/** The slice of HTMLAudioElement the player uses (tests pass a fake: jsdom cannot play). */
export interface AudioLike {
  src: string;
  currentTime: number;
  duration: number;
  paused: boolean;
  ended: boolean;
  volume: number;
  preload: string;
  play(): Promise<void>;
  pause(): void;
  addEventListener(type: string, cb: () => void): void;
}

type Listener = (payload: unknown) => void;

export const DEMO_DEVICE_ID = 'clouder-demo';

export class DemoPlayer {
  private readonly listeners = new Map<string, Listener[]>();
  private readonly loaded = new Map<string, Promise<string>>();
  private uri: string | null = null;
  private request = 0;

  constructor(
    /** Spotify track id → URL of its clip, or null when the demo has none. */
    private readonly clipFor: (spotifyId: string) => string | null,
    private readonly audio: AudioLike = new Audio(),
    /** Clip URL → a URL the <audio> element can seek in (see `blobUrl`). */
    private readonly load: (url: string) => Promise<string> = blobUrl,
  ) {
    audio.preload = 'auto';
    audio.volume = 0.8;
    // The SDK reports state on every change; `timeupdate` (~4×/s) also moves the scrub bar.
    for (const type of ['play', 'pause', 'timeupdate', 'seeked', 'loadedmetadata', 'ended']) {
      audio.addEventListener(type, () => this.emitState());
    }
  }

  // ── the Spotify.Player surface PlaybackProvider uses ──────────────────────

  connect(): Promise<boolean> {
    queueMicrotask(() => this.emit('ready', { device_id: DEMO_DEVICE_ID }));
    return Promise.resolve(true);
  }

  disconnect(): void {
    this.audio.pause();
  }

  addListener(event: string, cb: Listener): boolean {
    this.listeners.set(event, [...(this.listeners.get(event) ?? []), cb]);
    return true;
  }

  removeListener(event: string): boolean {
    return this.listeners.delete(event);
  }

  activateElement(): Promise<void> {
    return Promise.resolve();
  }

  pause(): Promise<void> {
    this.audio.pause();
    return Promise.resolve();
  }

  resume(): Promise<void> {
    // A browser may refuse playback before the first click or key press; the player then
    // simply stays paused and the next press of Play starts it.
    return this.audio.play().catch(() => this.emitState());
  }

  togglePlay(): Promise<void> {
    return this.audio.paused ? this.resume() : this.pause();
  }

  seek(positionMs: number): Promise<void> {
    this.audio.currentTime = positionMs / 1000;
    this.emitState();
    return Promise.resolve();
  }

  getCurrentState(): Promise<ReturnType<DemoPlayer['state']>> {
    return Promise.resolve(this.state());
  }

  setVolume(volume: number): Promise<void> {
    this.audio.volume = volume;
    return Promise.resolve();
  }

  getVolume(): Promise<number> {
    return Promise.resolve(this.audio.volume);
  }

  // ── what the Web API calls do in the demo ────────────────────────────────

  /** Start a track by its Spotify URI; false when the demo has no clip for it. */
  async playUri(uri: string): Promise<boolean> {
    const clip = this.clipFor(uri.split(':').pop() ?? '');
    if (!clip) return false;
    const request = ++this.request;
    this.uri = uri;
    this.audio.pause();
    const cached = this.loaded.get(clip) ?? this.load(clip);
    this.loaded.set(clip, cached);
    let src: string;
    try {
      src = await cached;
    } catch {
      // Offline or a missing file: stay paused; the next Play tries the download again.
      this.loaded.delete(clip);
      return true;
    }
    // Skipped past while downloading: the newer request plays instead.
    if (request !== this.request) return true;
    this.audio.src = src;
    this.audio.currentTime = 0;
    await this.resume();
    return true;
  }

  device(): SpotifyDevice {
    return {
      id: DEMO_DEVICE_ID,
      name: 'CLOUDER demo player',
      type: 'Computer',
      is_active: true,
      is_private_session: false,
      is_restricted: false,
      volume_percent: Math.round(this.audio.volume * 100),
    };
  }

  private state() {
    if (!this.uri) return null;
    const duration = Number.isFinite(this.audio.duration)
      ? Math.round(this.audio.duration * 1000)
      : 0;
    return {
      paused: this.audio.paused,
      // The SDK reports a finished track as paused at 0; PlaybackProvider advances on that.
      position: this.audio.ended ? 0 : Math.round(this.audio.currentTime * 1000),
      duration,
      track_window: { current_track: { uri: this.uri, album: { images: [] } } },
    };
  }

  private emitState(): void {
    const state = this.state();
    if (state) this.emit('player_state_changed', state);
  }

  private emit(event: string, payload: unknown): void {
    for (const cb of this.listeners.get(event) ?? []) cb(payload);
  }
}

/**
 * Every request a page makes goes through the MSW service worker, and Chrome cannot seek in
 * media served through one (`seekable` stays empty). A clip is fetched once and played from
 * a blob: URL, which the worker never sees.
 */
async function blobUrl(url: string): Promise<string> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`clip ${url}: ${res.status}`);
  return URL.createObjectURL(await res.blob());
}

/** The Spotify Web API calls `spotifyWebApi` makes, answered by the demo player. */
export function demoSpotifyApi(player: DemoPlayer) {
  const json = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
  const done = () => new Response(null, { status: 204 });

  return async (method: string, path: string, body: unknown): Promise<Response> => {
    const url = new URL(path, 'https://api.spotify.com');
    switch (`${method} ${url.pathname}`) {
      case 'PUT /v1/me/player/play': {
        const uri = (body as { uris?: string[] } | null)?.uris?.[0];
        if (!uri) {
          await player.resume();
          return done();
        }
        return (await player.playUri(uri))
          ? done()
          : json({ error: { status: 404, message: 'No clip in the demo' } }, 404);
      }
      case 'PUT /v1/me/player': // transfer: there is only the one device
        return done();
      case 'PUT /v1/me/player/pause':
        await player.pause();
        return done();
      case 'PUT /v1/me/player/seek':
        await player.seek(Number(url.searchParams.get('position_ms') ?? 0));
        return done();
      case 'GET /v1/me/player/devices':
        return json({ devices: [player.device()] });
      default: // e.g. cover lookups: the demo's tracks carry their artwork already
        return json({});
    }
  };
}
