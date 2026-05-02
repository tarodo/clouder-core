import { z } from 'zod';

// Matches ASCII C0 + DEL + C1 control bytes — these characters break
// rendering and storage; we reject them deliberately. eslint-disable
// the no-control-regex rule because the match is the whole point.
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f\x7f-\x9f]/;

export const categoryNameSchema = z
  .string()
  .trim()
  .min(1, 'name_required')
  .max(64, 'name_too_long')
  .refine((s) => !CONTROL_CHARS.test(s), 'name_control_chars');

export const createCategorySchema = z.object({ name: categoryNameSchema });
export const renameCategorySchema = createCategorySchema;

export type CreateCategoryInput = z.infer<typeof createCategorySchema>;
export type RenameCategoryInput = z.infer<typeof renameCategorySchema>;
