# Frontend UI Gotchas

Traps found during development, each documented with root cause and fix.

## Mantine 9 specifics

### `DatePickerInput type="range"` emits strings, not Dates

`@mantine/dates` `DatePickerInput` with `type="range"` and `valueFormat="YYYY-MM-DD"` emits `[string | null, string | null]` from its `onChange`, **not** `[Date | null, Date | null]`. The TypeScript types lie.

Zod schemas validating the tuple must accept both shapes:

```ts
const schema = z.object({
  dateRange: z.tuple([
    z.union([z.date(), z.string().min(1)]),
    z.union([z.date(), z.string().min(1)]),
  ]).transform(([a, b]) => [new Date(a), new Date(b)] as const),
});

// Use z.input<typeof schema> for the form value type (not z.infer).
type FormValues = z.input<typeof schema>;
```

Tuple-element Zod errors land at `form.errors['dateRange.0']` / `form.errors['dateRange.1']` — **not** at `form.errors.dateRange`. Check both keys when showing inline validation errors.

### `DatePickerInput` is undriveable in jsdom

`DatePickerInput` is a button + popover, not a text input. `userEvent.type` and `fireEvent.change` do not work.

Fix: mock the module at file scope in tests:

```ts
vi.mock('@mantine/dates', () => ({
  DatePickerInput: ({ onChange }: { onChange: (v: [Date, Date]) => void }) => (
    <input
      data-testid="date-range"
      onChange={(e) => {
        const [a, b] = e.target.value.split(' – ');
        onChange([new Date(a), new Date(b)]);
      }}
    />
  ),
}));
```

Real picker behaviour is left to E2E tests.

### `Title` has no `truncate` prop

Mantine 9 `Title` does not accept a `truncate` prop. Forwarding it produces a React unknown-prop warning and has no visible effect.

Fix: apply truncation inline:

```tsx
<Title style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
  {name}
</Title>
```

`Mantine` `Text` still supports `truncate="end"` — only `Title` lacks it.

### `setFieldValue` dropped the third options arg in 9.x

Mantine `form.setFieldValue` in version 9 accepts only `(field, value, { forceUpdate?: boolean })`. The third `{ validate: false }` option from earlier docs / plan code does not typecheck.

```ts
// WRONG — compile error in Mantine 9
form.setFieldValue('name', value, { validate: false });

// CORRECT
form.setFieldValue('name', value);
```

## TanStack Query 5

### Observers sharing `queryKey` share `queryFn` — latest registration wins

When two `useQuery` hooks register the same `queryKey`, TanStack Query 5 merges them into one observer. The **last-registered** `queryFn` is used for all fetches. If a passive hook registers a placeholder `queryFn` (e.g. `() => Promise.reject(new Error('cache only'))`) to prevent GC, it silently overrides the real fetching hook. Post-mutation refetches then reject instead of fetching.

Fix: instead of a passive no-fetch hook, configure the test `QueryClient` with `gcTime: Infinity`:

```ts
const queryClient = new QueryClient({
  defaultOptions: { queries: { gcTime: Infinity, retry: false } },
});
```

### `triageBlocksByStyleKey` helper, not literal tuples

When asserting on `invalidateQueries` spy calls, use the query key helper function (`triageBlocksByStyleKey(styleId, undefined)`) rather than writing the literal tuple. The helper resolves to `[..., 'all']` when the second argument is `undefined` — **not** `[..., undefined]`.

## Styling and link colours

### `<Text component={Link}>` inherits browser default link colours

Mantine `Text` does not override anchor styling when used as a link. The browser applies blue / visited-purple.

Fix: either set colours explicitly:

```tsx
<Text component={Link} c="var(--color-fg)" td="none" to="/path">
  Label
</Text>
```

Or use Mantine `<Anchor>`, which respects `theme.primaryColor` automatically.

### `just-tapped` is scale-only

`[data-just-tapped='true']` applies `transform: scale(0.97)` only — no colour change. An earlier iteration added an `accent-magenta` body class to flash the destination button on tap, but the magenta flash felt inconsistent with the otherwise monochrome UI and was removed.

If a future iteration reintroduces the colour flash, the body-class lifecycle in `CurateSessionPage` and the `background: var(--color-selected-bg)` rule in `DestinationButton.module.css` must be restored together — they form a pair. Neither works without the other.

## Hook rules and early Navigate

### Hooks after an early conditional return = lint error

Calling hooks after a conditional `<Navigate>` early return violates `react-hooks/rules-of-hooks` (ESLint catches it at CI). Example pattern in `CategoriesListPage` and `CategoryDetailPage`:

```tsx
// WRONG
function CategoriesListPage() {
  if (!styleId) return <Navigate to="/" />;
  const data = useSomeHook(); // hook after early return
}

// CORRECT: split into guard + inner component
function CategoriesListPage() {
  if (!styleId) return <Navigate to="/" />;
  return <CategoriesListPageInner />;
}

function CategoriesListPageInner() {
  const data = useSomeHook(); // always runs
  return <div>...</div>;
}
```

### `useCurateSession` exhaustive-deps warning is a known false positive

`frontend/src/features/curate/hooks/useCurateSession.ts` (around line 196) has a pagination `useEffect` that depends on `tracksQuery.hasNextPage`, `tracksQuery.isFetchingNextPage`, and `tracksQuery.fetchNextPage` — the stable primitives — rather than on the full `tracksQuery` object.

ESLint's `react-hooks/exhaustive-deps` flags `tracksQuery` as missing. Do **not** fix by adding the whole object to deps — it would re-run the effect on every render (the object reference changes every render even when data is stable). The comment in the file explains the reasoning.

## Cold-start auto-recovery

### Scheduler pattern

Two consumers exist: `pendingCreateRecovery.ts` (F2, matches by `(name, date_from, date_to)` tuple) and `pendingFinalizeRecovery.ts` (F4, matches by `block.status === 'FINALIZED'`).

Both follow the same pure scheduler shape:

```ts
function startRecovery({
  refetch,
  onSuccess,
  onFailure,
  delays = [2000, 5000, 10000],
}: RecoveryArgs): void {
  // No React. No QueryClient. Pure setTimeout chain.
}
```

- No React hooks, no QueryClient inside the scheduler itself.
- Caller passes `refetch` (function returning `Promise<data>`), `onSuccess(data)`, `onFailure()`, and optional `delays` array (ms between retry attempts).
- Caller decides what constitutes "success" and updates UI via callbacks.

When a third cold-start recovery use case arises, promote to a shared `frontend/src/lib/coldStartRecovery.ts` module (threshold: N = 3 consumers).
