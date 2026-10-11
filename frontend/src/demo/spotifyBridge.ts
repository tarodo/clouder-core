/**
 * Where the demo plugs its stand-in for the Spotify Web API. `spotifyWebApi` asks for it
 * only in demo builds, so the app never imports the demo player itself.
 */
export type DemoSpotifyApi = (method: string, path: string, body: unknown) => Promise<Response>;

let current: DemoSpotifyApi | null = null;

export function setDemoSpotifyApi(api: DemoSpotifyApi | null): void {
  current = api;
}

export function demoSpotifyApi(): DemoSpotifyApi | null {
  return current;
}
