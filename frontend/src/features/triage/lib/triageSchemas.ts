import { z } from 'zod';

// Matches ASCII C0 + DEL + C1 control bytes — these characters break
// rendering and storage; we reject them deliberately. eslint-disable
// the no-control-regex rule because the match is the whole point.
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f\x7f-\x9f]/;

export const triageNameSchema = z
  .string()
  .trim()
  .min(1, 'name_required')
  .max(128, 'name_too_long')
  .refine((s) => !CONTROL_CHARS.test(s), 'name_control_chars');

export const triageDateRangeSchema = z
  .tuple([z.date(), z.date()])
  .refine(([from, to]) => to.getTime() >= from.getTime(), 'date_range_invalid');

export const createTriageBlockSchema = z.object({
  name: triageNameSchema,
  dateRange: triageDateRangeSchema,
});

export type CreateTriageBlockInput = z.infer<typeof createTriageBlockSchema>;
