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

// Mantine 9 `DatePickerInput type="range"` emits `[string | null, string | null]`
// where the strings are ISO `YYYY-MM-DD`. Accept both strings and real Date
// instances; reject null/empty (those are "not picked yet" and surface as
// `date_range_required` in the dialog). Transform to a `[Date, Date]` tuple
// before the refine so `getTime()` works regardless of input shape.
const triageDateInput = z.union([z.date(), z.string().min(1)]);

export const triageDateRangeSchema = z
  .tuple([triageDateInput, triageDateInput])
  .transform(([from, to]) => [new Date(from), new Date(to)] as [Date, Date])
  .refine(([from, to]) => to.getTime() >= from.getTime(), 'date_range_invalid');

export const createTriageBlockSchema = z.object({
  name: triageNameSchema,
  dateRange: triageDateRangeSchema,
});

// Use `z.input` (not `z.infer`) so the form's value type matches what Mantine
// `DatePickerInput` emits (strings) before Zod coerces to Date on parse.
export type CreateTriageBlockInput = z.input<typeof createTriageBlockSchema>;
