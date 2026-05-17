# ADR-0009: Frontend stack — React 19 + Mantine 9
Status: Accepted
Date: 2026-05-17

## Context

CLOUDER's SPA needed a component library that could deliver a polished, production-grade UI without bespoke CSS for every component. The audience is a small DJ circle; the "pro tool" brand demands a clean, responsive, keyboard-navigable interface.

An early direction used **shadcn/ui** (headless Radix UI primitives + Tailwind CSS utility classes). The appeal was fine-grained control over markup. The friction was that every component needed explicit Tailwind class lists, theming required extensive CSS variable coordination, and the Tailwind JIT compiler's interaction with React testing utilities (jsdom + RTL) introduced setup complexity.

**Mantine 9** was chosen as the replacement. Mantine ships fully-styled, accessible components (forms, modals, date pickers, notifications, comboboxes) with a single theming entry point (`MantineProvider`). Design tokens flow in via `theme.colors`, `theme.fontFamily`, and CSS variables; the entire UI can be restyled without touching individual components. The component coverage matched the CLOUDER UI surface exactly — particularly `DatePickerInput`, `Select`, `Combobox`, and `Notifications`.

React 19, react-router 7, TanStack Query 5, and Vite 5 were chosen as the baseline because they represent the current stable generation of their respective ecosystems. TanStack Query 5's observer-sharing model (used throughout the curation and category features) and its `gcTime` / `staleTime` controls were specifically important for the curate cache invalidation pattern.

The one notable Tailwind remnant is utility-class usage inside CSS Modules for one-off layout tweaks; Tailwind itself is not in the project's dependencies.

## Decision

The SPA is built on React 19, Mantine 9, react-router 7, TanStack Query 5, and Vite 5. An earlier direction toward shadcn/ui + Tailwind was reversed; design tokens flow into a single MantineProvider theme.

## Consequences

- Mantine 9 ships opinionated component APIs that occasionally diverge from React conventions. Notable sharp edges: `DatePickerInput type="range"` emits `[string, string]` despite typing as `[Date, Date]`; `Slider` is undriveable in jsdom via `userEvent.type`; `Title` does not support a `truncate` prop. See `../frontend/testing.md` for the full test shim list.
- The test setup (`frontend/src/test/setup.ts`) requires six shims to make Mantine components work in jsdom. Adding a new Mantine component to a test file may require additional stubs (e.g. `document.fonts` for `Textarea` autosize).
- TanStack Query 5 changed the `vi.fn` mock form — use `vi.fn<() => Promise<T>>()`, not the legacy tuple form. Observers sharing a `queryKey` share a `queryFn`; a passive observer with a placeholder `queryFn` will override the real fetch.
- The feature-folder convention (`features/<feature>/{routes,components,hooks,lib}/`) was established alongside the stack choice and should be maintained for new features.
- Upgrading Mantine or TanStack Query to a future major version will likely require revisiting the test shims and the `DatePickerInput` mock pattern.

**Cross-references:** `../frontend/features.md`, `../frontend/testing.md`.
