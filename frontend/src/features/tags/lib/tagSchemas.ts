import { z } from 'zod';

// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f\x7f-\x9f]/;

export const tagNameSchema = z
  .string()
  .trim()
  .min(1, 'name_required')
  .max(64, 'name_too_long')
  .refine((s) => !CONTROL_CHARS.test(s), 'name_control_chars');

export const tagColorSchema = z.union([
  z.string().regex(/^#[0-9A-Fa-f]{6}$/, 'color_invalid'),
  z.null(),
]);

export const createTagSchema = z.object({
  name: tagNameSchema,
  color: tagColorSchema.optional().transform((v) => (v === undefined ? null : v)),
});

export const renameTagSchema = z
  .object({
    name: tagNameSchema.optional(),
    color: tagColorSchema.optional(),
  })
  .refine((v) => v.name !== undefined || v.color !== undefined, {
    message: 'payload_empty',
  });

export type CreateTagInput = z.infer<typeof createTagSchema>;
export type RenameTagInput = z.infer<typeof renameTagSchema>;
