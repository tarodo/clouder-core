import i18n from '../i18n';
import { demoHandlers } from './handlers';

export const DEMO_STRINGS = {
  playback: {
    reconnect_spotify: 'Playback needs Spotify — not available in the demo',
    open_device_picker: 'Everything else works on sample data',
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
