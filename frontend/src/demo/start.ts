import i18n from '../i18n';
import { DemoDb } from './db';
import { demoHandlers } from './handlers';
import { DemoPlayer, demoSpotifyApi } from './player';
import { setDemoSpotifyApi } from './spotifyBridge';

const NOT_IN_DEMO = 'Not available in the demo — it runs on sample data in your browser.';

/** English overrides: refused writes read as "not in the demo", not as errors. */
export const DEMO_STRINGS = {
  errors: { forbidden: NOT_IN_DEMO, unknown: NOT_IN_DEMO },
  triage: { toast: { generic_error: NOT_IN_DEMO } },
  categories: { toast: { generic_error: NOT_IN_DEMO } },
  playlists: { toast: { generic_error: NOT_IN_DEMO }, copy: { failed: NOT_IN_DEMO } },
};

/**
 * Playback: the demo player takes the place of the Spotify SDK (its `window.Spotify`
 * global, which PlaybackProvider constructs) and of the Web API (through the bridge).
 */
function installPlayer(db: DemoDb): void {
  const clips = `${import.meta.env.BASE_URL}audio/`;
  const player = new DemoPlayer((spotifyId) => {
    const clip = db.clipFor(spotifyId);
    return clip ? clips + clip : null;
  });
  (window as unknown as { Spotify: unknown }).Spotify = {
    // `new Spotify.Player(...)` returns this object: a constructor may return one.
    Player: function DemoSpotifyPlayer() {
      return player;
    },
  };
  setDemoSpotifyApi(demoSpotifyApi(player));
}

/** Start the in-browser API before React mounts: AuthProvider fetches on mount. */
export async function startDemo(): Promise<void> {
  const db = new DemoDb();
  const { setupWorker } = await import('msw/browser');
  await setupWorker(...demoHandlers(db)).start({
    serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
    onUnhandledRequest: 'bypass',
    quiet: true,
  });
  installPlayer(db);
  i18n.addResourceBundle('en', 'translation', DEMO_STRINGS, true, true);
}

export { DemoBanner } from './DemoBanner';
