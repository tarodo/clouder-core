// frontend/src/features/playlists/lib/playlistSchemas.ts
import { z } from 'zod';

// Matches ASCII C0 + DEL + C1 control bytes. eslint-disable
// because the regex existence is intentional.
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f\x7f-\x9f]/;

export const playlistNameSchema = z
  .string()
  .trim()
  .min(1, 'name_required')
  .max(100, 'name_too_long')
  .refine((s) => !CONTROL_CHARS.test(s), 'name_control_chars');

export const playlistDescriptionSchema = z
  .union([z.string().max(300, 'description_too_long'), z.null()])
  .transform((v) => (typeof v === 'string' && v.trim() === '' ? null : v));

export const createPlaylistSchema = z.object({
  name: playlistNameSchema,
  description: playlistDescriptionSchema.optional(),
  is_public: z.boolean().default(false),
});

export const playlistStatusSchema = z.enum(['active', 'completed']);

export const patchPlaylistSchema = z
  .object({
    name: playlistNameSchema.optional(),
    description: playlistDescriptionSchema.optional(),
    is_public: z.boolean().optional(),
    status: playlistStatusSchema.optional(),
  })
  .refine(
    (v) =>
      v.name !== undefined ||
      v.description !== undefined ||
      v.is_public !== undefined ||
      v.status !== undefined,
    { message: 'at_least_one_field' },
  );

export type CreatePlaylistInput = z.infer<typeof createPlaylistSchema>;
export type PatchPlaylistInput = z.infer<typeof patchPlaylistSchema>;
