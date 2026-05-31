const ID_RE = /^[A-Za-z0-9_-]{11}$/;

/** Extract an 11-char YT video id from a URL or a bare id; null if none. */
export function parseYtVideoId(input: string): string | null {
  const s = input.trim();
  if (ID_RE.test(s)) return s;
  try {
    const u = new URL(s);
    const host = u.hostname.replace(/^www\./, '');
    if (host === 'youtu.be') {
      const id = u.pathname.slice(1);
      return ID_RE.test(id) ? id : null;
    }
    if (host === 'youtube.com' || host === 'music.youtube.com' || host === 'm.youtube.com') {
      const v = u.searchParams.get('v');
      return v && ID_RE.test(v) ? v : null;
    }
  } catch {
    return null;
  }
  return null;
}
