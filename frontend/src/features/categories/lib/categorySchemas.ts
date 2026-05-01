import { z } from 'zod';

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
