# i18n

`react-i18next` initialised in `index.ts`. Iter-2a ships **EN-only**; RU lands in iter-2b.

## Domain terms — never translate

`NEW`, `OLD`, `NOT`, `DISCARD`, `UNCLASSIFIED`, `FINALIZED`, `BPM`, `key`. Drop these into JSX as plain strings.

## Adding keys

- Pick a flat-by-screen key like `triage.create_block`.
- Add to `en.json`.
- Use via `const { t } = useTranslation(); t('triage.create_block')`.
- For dynamic content: `t('user_menu.signed_in_as', { name: state.user.display_name })`.

## Adding a language (iter-2b)

1. Create `ru.json` next to `en.json` with the same key shape.
2. Register in `index.ts`: `resources: { en, ru }`.
3. Wire a language toggle in Profile (separate ticket).
