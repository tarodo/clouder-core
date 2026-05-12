import type { TFunction } from 'i18next';

export const PLAYLIST_FIELD_ERROR_KEYS: Record<string, string> = {
  name_required: 'playlists.errors.name_required',
  name_too_long: 'playlists.errors.name_too_long',
  name_control_chars: 'playlists.errors.name_control_chars',
  description_too_long: 'playlists.errors.description_too_long',
};

export function translateFieldError(
  code: string | undefined,
  t: TFunction,
): string | undefined {
  if (!code) return undefined;
  const key = PLAYLIST_FIELD_ERROR_KEYS[code];
  return key ? t(key) : code;
}
