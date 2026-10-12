// Set by playback while music plays: a hidden tab must still refresh then,
// since the Spotify SDK and Web API calls need fresh tokens mid-playback.
let keepAlive = false;

export function setSessionKeepAlive(value: boolean): void {
  keepAlive = value;
}

export function sessionKeepAlive(): boolean {
  return keepAlive;
}
