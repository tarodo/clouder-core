import i18n from '../i18n';
import { demoHandlers } from './handlers';

const NOT_IN_DEMO = 'Not available in the demo — it runs on sample data in your browser.';

/** English overrides: refused writes read as "not in the demo", not as errors. */
export const DEMO_STRINGS = {
  errors: { forbidden: NOT_IN_DEMO, unknown: NOT_IN_DEMO },
  triage: { toast: { generic_error: NOT_IN_DEMO } },
  categories: { toast: { generic_error: NOT_IN_DEMO } },
  playlists: { toast: { generic_error: NOT_IN_DEMO }, copy: { failed: NOT_IN_DEMO } },
  playback: {
    reconnect_spotify: 'Playback needs Spotify — not in the demo',
    open_device_picker: 'why',
    devices: { connecting: 'Playback runs through Spotify Connect, which the demo leaves out.' },
  },
};

/** Start the in-browser API before React mounts: AuthProvider fetches on mount. */
export async function startDemo(): Promise<void> {
  const { setupWorker } = await import('msw/browser');
  await setupWorker(...demoHandlers()).start({
    serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
    onUnhandledRequest: 'bypass',
    quiet: true,
  });
  i18n.addResourceBundle('en', 'translation', DEMO_STRINGS, true, true);
}

export { DemoBanner } from './DemoBanner';
