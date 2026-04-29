# Mantine 7 → 9 Migration Notes · CLOUDER iter-2a

> Source-of-truth list of Mantine breaking changes that affect this handoff. Read first if you wrote a code snippet referencing Mantine 7 idioms.

## Decision: do NOT use `v8CssVariablesResolver`

Mantine 9 changed the colour math behind `variant="light"` (lighter, less saturated than 8.x). We accept the new defaults. Rationale:

- CLOUDER ramp is monochrome neutral; the visible delta on `variant="light"` is tiny against a no-saturation palette.
- `v8CssVariablesResolver` is a temporary escape hatch documented to be removed in 10.x. Building on it now creates a second migration.

Escape hatch (only if visual QA finds a critical regression):

```tsx
import { MantineProvider, v8CssVariablesResolver } from '@mantine/core';
<MantineProvider cssVariablesResolver={v8CssVariablesResolver}>...
```

## Breaking changes that touch this handoff

| Area | 7.x | 9.x | Where it shows up |
|---|---|---|---|
| Form resolvers | `import { zodResolver } from '@mantine/form'` | `import { schemaResolver } from '@mantine/form'` + `zod/v4` | P-15 Create Triage Block form |
| `@mantine/dates` values | `onChange(date: Date)` | `onChange(value: string)` (YYYY-MM-DD) | P-15 `date_from`/`date_to` |
| `Collapse` toggle prop | `<Collapse in={open}>` | `<Collapse expanded={open}>` | Anywhere expandable rows are added (currently none in spec, future-proofing) |
| `useMutationObserver` hook | Single hook with optional target arg | Renamed `useMutationObserverTarget` when target is required | Internal — only matters if a custom hook needs DOM observation |
| `Carousel` config | Props `loop`, `dragFree`, `align` | `emblaOptions={{ loop, dragFree, align }}` | Not used in iter-2a; note for future |
| HTML hydration | manual `lang` only | spread `mantineHtmlProps` on `<html>` | App root (READMEs updated) |
| Light variant colour math | 8.x ramp | 9.x ramp (lighter) | Badges (`variant="light"`), buttons with `variant="light"` |

## Spec snippet patches

These edits are applied directly in `04 Component spec sheet.html` (Task 6 of the implementation plan). Listed here as a single source of truth.

### DatePicker — `onChange` returns string

Current snippet implies `Date`:

```tsx
<DatePickerInput value={value} onChange={setValue} />
```

In 9.x the second arg is `string | null` (e.g. `'2026-04-29'`). Three integration patterns:

1. **Native string state** (recommended, no conversion):
   ```tsx
   const [value, setValue] = useState<string | null>(null);
   <DatePickerInput value={value} onChange={setValue} />
   ```

2. **Date state with conversion** (when downstream needs `Date`):
   ```tsx
   const [value, setValue] = useState<Date | null>(null);
   <DatePickerInput
     value={value ? value.toISOString().slice(0, 10) : null}
     onChange={(v) => setValue(v ? new Date(v) : null)}
   />
   ```

3. **Timezone-aware via dayjs**:
   ```tsx
   import dayjs from 'dayjs';
   const dateInTz = dayjs(value).tz('Europe/Berlin').toDate();
   ```

### Form validation — `schemaResolver` instead of `zodResolver`

P-15 Create Triage Block form (the only form with non-trivial validation in iter-2a):

```tsx
import { useForm, schemaResolver } from '@mantine/form';
import { z } from 'zod/v4';

const schema = z.object({
  name: z.string().min(1, { error: 'Name required' }),
  style: z.string().min(1, { error: 'Style required' }),
  date_from: z.string().min(1, { error: 'Start date required' }),
  date_to: z.string().min(1, { error: 'End date required' }),
});

const form = useForm({
  initialValues: { name: '', style: '', date_from: '', date_to: '' },
  validate: schemaResolver(schema, { sync: true }),
});
```

Note `zod/v4` import path — Mantine 9 expects Standard Schema, which Zod 4 implements.

### Button focus override

Current spec mentions `--mantine-color-blue-filled` as the variable to override. In Mantine 9 the variable is rebased onto `primaryColor` (renamed `--mantine-primary-color-filled`). Practical guidance: **do nothing**. CLOUDER's CSS-variable layer in `tokens.css` (`--color-border-focus`) supersedes Mantine's focus-ring colour through the component CSS in `theme.ts` defaults; no Mantine-internal override is required.

## Versions to install

```bash
pnpm add @mantine/core@9 @mantine/hooks@9 @mantine/dates@9 @mantine/notifications@9 @mantine/form@9 dayjs zod react-i18next i18next @tabler/icons-react
```

`@mantine/carousel` is NOT installed — not used in iter-2a.

## Migration checklist (frontend)

- [ ] `<html {...mantineHtmlProps} lang="en">` at app root.
- [ ] `<ColorSchemeScript defaultColorScheme="light" />` in `<head>` (matches `MantineProvider` setting — see `Q1` in OPEN_QUESTIONS).
- [ ] All `@mantine/dates` callbacks treated as `string`, not `Date`.
- [ ] If a form is added beyond P-15, validation goes through `schemaResolver` (not `zodResolver`).
- [ ] If a `<Collapse>` is added, prop is `expanded` (not `in`).
- [ ] No usage of `v8CssVariablesResolver` unless a visual regression is reported and triaged.
