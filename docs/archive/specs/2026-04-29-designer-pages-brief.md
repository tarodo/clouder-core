# CLOUDER · Pages Brief (Iteration 2)

> Brief for the designer to deliver all production-ready pages on top of the sprint-1 Design System (`docs/CLOUDER Design System _standalone_.html`).

**Date:** 2026-04-29
**Author:** Roman (product / engineer)
**Audience:** UI/UX designer for CLOUDER
**Predecessor:** [`2026-04-28-clouder-design-system-brief.md`](./2026-04-28-clouder-design-system-brief.md) — sprint-1, the delivered Design System (Studio Mono, monochrome `oklch`, light/dark, optional magenta accent, Geist + Geist Mono).
**Product logic sources:**
- [`2026-04-25-spec-A-user-auth-design.md`](./2026-04-25-spec-A-user-auth-design.md) — auth, profile, sessions.
- [`2026-04-26-spec-C-categories-design.md`](./2026-04-26-spec-C-categories-design.md) — categories.
- [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) — triage + finalize.
- [`2026-04-25-old-version-feature-parity-design.md`](./2026-04-25-old-version-feature-parity-design.md) — adjacent layers (Layer 3 release-playlists not yet built; only a nav stub is reserved).
- API contract: `docs/openapi.yaml`. Frontend guide: `docs/frontend.md`.

---

## 1. What sprint-1 already covers (do not redraw)

The sprint-1 deliverable (`docs/CLOUDER Design System _standalone_.html`) contains:

- **Foundations:** tokens (color/neutral oklch, type 11–32, space 0–20, radius xs–full, shadows sm/md, motion fast/base/slow/pulse, control-sm/md/lg/xl), wordmark.
- **Base catalog:** Button, Input, Select, Tabs, Card, Badge, Table, ListItem, Skeleton, Toast, Dialog, Sheet, Popover, Tooltip, Progress, Avatar, EmptyState, Separator, Breadcrumb, Switch, Checkbox, Radio.
- **Product catalog:** TrackRow (compact + regular), DestinationButton (idle/hover/primary/just-tapped/disabled + hotkey hint), PlayerCard (full + sticky mini), NowPlayingDot, CategoryPill, StyleSelector, TriageBucket, BlockHeader, CollectionStat, HotkeyHint, AppShell.
- **Anchor scenes:** Player + Curate mobile (light + dark), Player + Curate desktop (light + dark + accent), Triage Block detail.

Anchor scenes are **direction, not the final shipping screen.** Iteration 2 redraws the production form of every page that uses them (see §3.6).

If a page needs a component not present in the sprint-1 DS, it is added as an explicit variant of an existing component, not as a fresh component, and listed in the deliverable §5 delta-report.

---

## 1.5. Tech context update (changes since sprint-1)

The frontend stack is now **Mantine** (`@mantine/core` + `@mantine/dates` + `@mantine/hooks`) — not shadcn/ui or Tailwind v4 as previously stated in the sprint-1 brief Section 2. Sprint-1 brief is otherwise valid (tokens, type, density, motion, wordmark) but its tech-stack paragraph is **superseded** by this document.

Implications for the designer:

- **Floor library:** Mantine plays the role shadcn/ui played in sprint-1 — it provides accessible primitives (Modal, Combobox, Notifications, Tabs, ScrollArea, Menu, DatePicker, etc.). The CLOUDER DS sits on top: every base component in the sprint-1 catalog is a Mantine wrapper styled by CLOUDER tokens.
- **DatePicker:** the sprint-1 DS lacks one. Mantine `@mantine/dates` `DatePickerInput` / `DateInput` is the reference implementation; the designer specs the visual treatment using CLOUDER tokens.
- **Token export:** tokens must compile to **two** targets:
  1. `tokens.css` (CSS custom properties, light + dark) — used by global styles.
  2. A `MantineProvider` theme object (TypeScript) — same colour / space / radius / font scales, exposed as Mantine theme keys. Designer ships colour and primitive-token mapping; the engineer wires `MantineProvider`.
- **Iconography:** Mantine ships with `@tabler/icons-react`. CLOUDER DS direction (Lucide / Phosphor) is preserved — the designer chooses one set, and the engineer aliases it through Mantine's icon API.

---

## 2. User journey

This is the story that connects screens. Each step → one or more pages in §3.

```
[1] Land → /login (no session)
       │
       ▼
[2] Sign in via Spotify OAuth (Premium-gated) → callback returns JSON, redirects to /
       │
       ▼
[3] Home / Dashboard
   ├── active triage blocks for the current week
   ├── current style + style switcher
   ├── shortcut to Categories and last finalize
   └── CTA "New triage" if no block exists this week
       │
       ▼
[4] Manage categories (if missing) → Categories list (per style)
   ├── create category (modal)
   ├── rename
   ├── reorder (↑ / ↓ buttons, no DnD)
   └── soft-delete (with confirmation)
       │
       ▼
[5] Create a triage block for (style, week)
   ├── modal / sheet: style + name + date_from / date_to
   ├── on submit — pending state (may take >5 s on cold start)
   └── on response → Triage Block detail
       │
       ▼
[6] Triage Block detail
   ├── header: style · week · per-bucket counters · finalize CTA
   ├── lanes: NEW · OLD · NOT · UNCLASSIFIED · DISCARD · STAGING-per-category
   └── inactive staging buckets carry a "deleted category" badge
       │
       ▼
[7] Open a bucket → Bucket detail (or jump into the Player)
   ├── search + pagination
   ├── multi-select tracks
   └── action: Move / Transfer
       │
       ▼
[8] Curate (heart of the product) — Player + DestinationButton grid
   ├── listen 30–60 s
   ├── one tap on a DestinationButton → track lands in staging-X / DISCARD
   ├── hotkeys 1–9 on desktop, tap on mobile
   └── auto-advance to the next track
       │
       ▼
[9] Move tracks
   ├── Move (intra-block) — sheet to pick a target bucket
   └── Transfer (cross-block) — sheet to pick a target block + bucket
       │
       ▼
[10] Finalize
   ├── inactive-staging-with-tracks → 409 page with remediation
   ├── happy path → success view with per-category promoted counts
   └── block flips to FINALIZED (read-only history)
       │
       ▼
[11] Categories grew → DJ returns to [3]
```

Outside the main loop:

- **Profile / Settings** — session management, theme, account. *(iter-2b)*
- **Browse / Catalog** — read the canonical core (`/tracks`, `/artists`, `/albums`, `/labels`). *(iter-2b)*
- **Admin** (`is_admin = true` only) — `POST /collect_bp_releases`, `GET /runs/{run_id}`, `/tracks/spotify-not-found`. *(iter-2b)*

---

## 3. Pages and states — Iteration 2a (this sprint)

Every page is delivered in **light + dark** themes. Mobile target 360–430 px. Desktop target 1280–1440 px. AppShell stays the global frame (top bar + content + mobile bottom tab bar).

Format: **purpose → DS components used → mobile / desktop differences → states (loading / empty / error / edge)**.

### 3.1 Auth & onboarding

| ID | Page | Purpose | Components | Mobile / Desktop | States |
|---|---|---|---|---|---|
| **P-01** | `/login` | "Sign in with Spotify" + Premium-required disclaimer | Button (primary lg), Wordmark, body text, footer disclaimer | Identical center-card | default · pending (after click, before redirect) · error: "Spotify Premium required" · error: "Sign-in failed" |
| **P-02** | `/auth/callback` (transient) | Loader while the SPA reads JSON and redirects | Skeleton + Wordmark + tagline | Same | loading-only (≥10 s tolerance — see B7) |
| **P-03** | Premium-required | When the Spotify account lacks Premium | EmptyState + CTA "Try another account" | Same | static |

### 3.2 Shell

| ID | Page | Purpose | Components | Mobile / Desktop | States |
|---|---|---|---|---|---|
| **P-04** | AppShell | Global frame: top bar (CLOUDER + StyleSelector + theme toggle + Avatar with menu), content area, mobile bottom tabs (`Home / Curate / Library`). Library tab opens an EmptyState "Coming soon" until iter-2b lands. **Avatar menu** carries Profile + Sign out + Admin (visible only when `is_admin = true`); each menu item links to an iter-2b stub or directly signs out. The Avatar menu is the home for everything that is not bottom-tab-worthy. | AppShell, StyleSelector, Avatar, Switch (theme), Popover/Menu | Mobile: bottom tabs + Avatar menu in top bar · Desktop: side rail or top nav + Avatar menu (designer picks one nav layout and documents the choice in the README delta) | default · scroll-shadow on top-bar · "no style selected" · admin vs non-admin avatar menu |

### 3.3 Home / Dashboard

| ID | Page | Purpose | Components | Mobile / Desktop | States |
|---|---|---|---|---|---|
| **P-08** | `/` Home | Entry point after login. Shows: current style (StyleSelector), active triage blocks (Card list), last finalize summary (CollectionStat), shortcut to Categories, CTA "New triage" if none exists this week. | StyleSelector, Card, BlockHeader (compact variant), CollectionStat, Button (primary), EmptyState | Mobile: vertical stack · Desktop: 2-col (active blocks left / stats + categories shortcut right) | default · empty (new user, no styles) · no-active-blocks · loading skeleton |

### 3.4 Categories (Layer 1)

| ID | Page | Purpose | Components | Mobile / Desktop | States |
|---|---|---|---|---|---|
| **P-09** | Categories list (per style) | All categories for the current style ordered by `position`. Reorder via ↑ / ↓ buttons, rename, delete, create. **No drag-and-drop.** | CategoryPill, Button (ghost icon ↑ / ↓), Button (primary "New"), EmptyState | Mobile: vertical list, action sheet on long-press · Desktop: list with inline ↑ / ↓ + actions on hover | default · empty · loading · error toast |
| **P-10** | Category detail | Track list inside a category, search, pagination, remove track, "added from triage X" badge. | TrackRow (compact), Input (search), Tag (source badge), Button (icon trash) | Mobile: TrackRow in two lines + meta row · Desktop: table density | default · empty · search-no-results · pagination loading · remove-confirm Dialog |
| **P-11** | Create category modal | Single input (name), submit. | Dialog, Input, Button | Sheet on mobile · Dialog on desktop | default · validating · 409 name-conflict (inline error) · submitting |
| **P-12** | Rename category modal | Same layout, prefilled name. | Dialog, Input | Same | default · 409 name-conflict |
| **P-13** | Delete category dialog | Soft-delete confirmation. If an active triage already has a staging bucket with tracks for this category, surface a warning ("tracks remain; the bucket will become inactive"). | Dialog (alert variant), Button (destructive) | Same | default · with-warning · submitting |

### 3.5 Triage Blocks (Layer 2)

| ID | Page | Purpose | Components | Mobile / Desktop | States |
|---|---|---|---|---|---|
| **P-14** | Triage Blocks list | All blocks for the user. Filter: status (IN_PROGRESS / FINALIZED). Sort: created_at DESC. Each item is a compact card: name, week range, style, total tracks, status badge. | Card, Tabs (status filter), Badge (status), CollectionStat (mini) | Mobile: stacked cards · Desktop: 2–3 col grid | default · empty · only-finalized · loading · pagination |
| **P-15** | Create Triage Block sheet/modal | Form: style (Select), name (Input), `date_from` + `date_to` (DatePicker — see B11). Long-running submit can take >5 s on cold start. **Edge case:** if an IN_PROGRESS block already exists for the same `(style, overlapping window)`, render a pre-submit warning "Existing block detected for this style and window. Open existing or create another?" with two CTAs (`Open existing`, `Create another`). | Dialog, Select, Input, DatePicker, Button (primary lg) | Sheet on mobile · Dialog on desktop | default · validating (`date_to >= date_from`) · long-running pending (skeleton, 5–10 s) · 503 hint "creation may have succeeded — check the list" · pre-submit warning (overlap detected) · success → P-16 |
| **P-16** | Triage Block detail | Top: BlockHeader (name + style + date range + finalize CTA + per-bucket counters). Body: lane list of buckets in fixed order `NEW · OLD · NOT · UNCLASSIFIED · DISCARD · STAGING[*]`. Each bucket: header + counter + 3–5 track preview + "Open" link. Inactive staging carries a "deleted category" badge. | BlockHeader, TriageBucket, TrackRow (compact), Badge (inactive), Button (primary "Finalize") | Mobile: vertical stack of buckets, sticky BlockHeader · Desktop: horizontal lane grid (5–6 lanes scrollable) or vertical sections — designer picks and documents | default · empty bucket · all-empty (just-created, no matches) · finalized read-only · soft-deleted (404 fallback) |
| **P-17** | Bucket detail | Full track list of one bucket. Search, pagination, multi-select. Bottom action bar: `Move`, `Transfer`, `Open in Player`. | TrackRow (with checkbox), Input (search), Button (toolbar), Sheet (action bar) | Mobile: full-screen list + sticky action bar · Desktop: split view (list left / preview right — optional) | default · empty · search-no-results · multi-select active · pagination loading · 422 cap-1000 inline error |
| **P-18** | Move sheet (intra-block) | `from_bucket` → `to_bucket` for N selected tracks. Target list = all buckets of the block except `from` and any inactive bucket. | Sheet, ListItem (selectable), Button (primary) | Bottom sheet (mobile) / right sheet (desktop) | default · target-inactive disabled · submitting · result toast |
| **P-19** | Transfer sheet (cross-block) | Two-step wizard: 1) pick target block (IN_PROGRESS, same style); 2) pick target bucket. | Sheet, ListItem, Button, Tabs (two steps) | Same | step-1 · step-2 · empty (no other IN_PROGRESS blocks) · 422 style-mismatch · submitting · result toast |
| **P-20** | Finalize confirmation | Confirmation step. Sum per staging category ("Tech House: 12 → category", "Deep: 5 → category"). Long-running on large staging buckets. | Dialog, ListItem, Button (primary lg) | Same | default · submitting · long-running pending · success (per-category promoted counts) |
| **P-21** | Finalize blocked (409) | Inactive staging bucket(s) hold tracks. **Primary CTA:** "Move all to DISCARD" (bulk action calling `POST /triage/blocks/{id}/move` per offending bucket). **Secondary:** "Open bucket" → P-17 for manual handling. List the offenders with `track_count`. | Dialog (alert), ListItem, Button (primary "Move all to DISCARD"), Button (link → P-17) | Same | default · bulk-submitting · per-bucket result toast |

### 3.6 Player + Curate — full production redraw

The sprint-1 anchor scenes are **redrawn end to end**. They proved the system; iter-2a delivers shipping screens covering every state.

| ID | Page | Purpose | Components | Mobile / Desktop | States (each in light + dark) |
|---|---|---|---|---|---|
| **P-22** | Curate Mobile (full) | Production mobile Curate. Designer redraws happy-path + every state. | DestinationButton, PlayerCard, HotkeyHint, NowPlayingDot, EmptyState | Mobile only | Destination layouts: 0 (no categories — EmptyState with CTA to create) · 1–9 destinations · 10+ destinations (overflow strategy: horizontal scroll or 2-row grid — designer picks) · long category names truncation · just-tapped pulse (3-frame motion sample). Player states: idle · playing · buffering · paused · error (Spotify SDK timeout) · disconnected (lost device). |
| **P-23** | Curate Desktop (full) | Production desktop Curate. Hotkey hints under each DestinationButton, keyboard-shortcut tooltip pattern, left column showing current bucket / block context. | Same as P-22 + Tooltip (keyboard variant), CategoryPill | Desktop only | Same destination layouts as P-22 + hotkey-conflict warning when destinations > 9. Same six player states. |
| **P-24** | Mini-player | Sticky bottom (mobile) / bottom-right (desktop) for non-Curate pages. Cover + title + transport + progress. | PlayerCard (compact variant) | Both | default · paused · buffering · disconnected |
| **P-25** | Player connect / device picker | Web Playback SDK not ready, or user must pick a device ("open Spotify, transfer playback to CLOUDER"). | EmptyState + ListItem (device) + Button | Same | not-connected · waiting-handoff · multi-device · error |

### 3.7 System patterns (cross-cutting)

These are universal; the designer delivers **one canonical example each**, reused by reference (B6).

| ID | Pattern | Coverage |
|---|---|---|
| **S-01** | Loading skeletons | Track list · Bucket lane · Card grid · Player. At least three exemplars. |
| **S-02** | Empty states | New user (no styles) · No categories · No triage blocks · No tracks in bucket · Search no-results · Coming soon. One exemplar each. |
| **S-03** | Error envelope toast | `{error_code, message, correlation_id}` → Toast: message + secondary `code: <error_code>` + copy-correlation-id action. |
| **S-04** | 503 cold-start banner | Global banner "Backend warming up — retry shortly" with auto-retry indicator. |
| **S-05** | "Creation may have succeeded" hint | Inline banner shown after a 503 on `POST /triage/blocks` or `POST /collect_bp_releases`. CTA "Refresh list". |
| **S-06** | Destructive confirm dialog | Single pattern for delete / finalize / sign-out: Dialog · destructive Button · consequence copy. |
| **S-07** | Multi-select toolbar | Sticky bottom action bar when ≥1 item selected: count + actions + cancel. |
| **S-08** | Hotkey overlay | `?` or `Cmd+/` opens a Popover/Sheet listing all shortcuts for the current screen. |
| **S-09** | Mobile sheet vs desktop dialog | Same content rendered as bottom Sheet on mobile, Dialog on desktop. Designer ships both renderings on at least one example (P-15 or P-18). |
| **S-10** | Inactive / deleted-category badge | Universal "this entity is soft-deleted" treatment used in P-13, P-16, P-17. |

---

## 4. Iteration 2b (next sprint, separate brief)

The following pages are deliberately **out of iter-2a scope.** A separate brief will follow.

| ID | Page | Reason for deferral |
|---|---|---|
| **P-05** | `/me` Profile + sessions | Not on the critical curation path. |
| **P-06** | Theme & accent settings | Theme toggle is wired into AppShell (P-04); the dedicated settings page can wait. |
| **P-07** | 404 / generic error | A minimal text-only fallback ships first; the designed version follows. |
| **P-26** | Tracks browse | Catalog browsing is a secondary read-only flow. |
| **P-27** | Artists / Albums / Labels list | Same as P-26. |
| **P-28** | Style index | Currently surfaced as StyleSelector content; the standalone page is iter-2b. |
| **P-29** | Admin: Collect Releases | Admin-only, used from desktop, low daily traffic. Sensitive `bp_token` input variant designed in iter-2b. |
| **P-30** | Admin: Run Status | Admin-only. |
| **P-31** | Admin: Spotify-not-found | Admin-only debug surface. |
| **P-32** | Layer-3 (release playlists) nav stub | Layer-3 spec not finalized. |

The iter-2a AppShell (P-04) reserves nav slots for these pages so the navigation already feels complete; the slots open onto an EmptyState "Coming soon" until iter-2b lands.

---

## 5. Out of scope (both iterations)

To save the designer's time:

- Onboarding tours, hint carousels.
- Marketing / landing.
- Notification center / inbox.
- Drag-and-drop triage. CLOUDER deliberately ships no DnD (see §2 — tap-only curation).
- Native iOS / Android shells.
- Lottie / video transitions.
- Layer 3 (release playlists) beyond the nav stub P-32.
- Full UI localization (English copy only this sprint; Cyrillic glyph support comes from Geist `unicode-range U+0400–045F` already in DS).

---

## 6. Deliverables

1. **Pages catalog** — same tool family as sprint-1. Structure: `00 · Cover` · `01 · Auth` · `02 · Shell` · `03 · Home` · `04 · Categories` · `05 · Triage` · `06 · Player & Curate` · `07 · System States` · `99 · Iter-2b stubs`. Every page renders in light + dark.
2. **Component coverage report (README delta)** — list of (a) DS components extended with new variants, (b) any newly proposed components, (c) deviations from sprint-1 tokens.
3. **Tokens delta** — if a token, variant, or component is added, update `tokens.css` **and** the `MantineProvider` theme object. No regression to sprint-1.
4. **DatePicker** — formal DS variant (foundations + tokens + states). Mantine `@mantine/dates` is the reference implementation; visual treatment uses CLOUDER tokens.
5. **Flow map** — one diagram visualizing §2 user journey with arrows between page-IDs. Inside the catalog tool.
6. **Hotkey / keyboard map** — table of desktop Curate hotkeys (1–9, Space, ←/→, J/K) referencing the HotkeyHint component.

---

## 7. Acceptance criteria

| # | Criterion |
|---|---|
| **B1** | Every iter-2a page-ID has light + dark variants × mobile + desktop variants where listed in §3. |
| **B2** | Every interactive page provides at minimum: `default`, `loading`, `empty` (where applicable), `error` states. |
| **B3** | Every component on a page is an instance of a sprint-1 DS component or an explicit variant of one. New variants are listed in §6 deliverable 2 (delta-report). |
| **B4** | All interactive elements on mobile have ≥44 px tap targets. |
| **B5** | Both themes meet WCAG AA contrast: ≥4.5:1 body text, ≥3:1 UI controls and large text. |
| **B6** | System patterns S-01..S-10 are illustrated exactly once and reused by reference; not redrawn per page. |
| **B7** | Every page that issues a long-running call (P-02, P-15, P-20) shows a pending state with ≥10 s tolerance and includes the "creation may have succeeded — refresh" copy variant where applicable. |
| **B8** | P-16 and P-17 visually distinguish active vs inactive staging buckets via S-10. |
| **B9** | P-22 and P-23 each show: 0 / 1–9 / 10+ destination layouts × player states {idle, playing, buffering, paused, error, disconnected} × light + dark. |
| **B10** | The flow map (deliverable §5) connects all iter-2a page-IDs without orphan nodes. |
| **B11** | DatePicker is delivered as a formal DS variant before P-15 is shipped. Mantine `@mantine/dates` is the reference; visuals use CLOUDER tokens. |
| **B12** | Tokens compile to **both** `tokens.css` (light + dark CSS custom properties) and a `MantineProvider` theme object, with the same colour / space / radius / font scales. No DS-only or stack-only values. |

---

## 8. Process

- **Kickoff (~30 min):** walk §2 + §3 together, agree on the order: Auth → Home → Categories → Triage list → Triage detail → Curate (full redraw) → System patterns.
- **Mid-point review (~7 days in):** Auth + Home + Categories + Triage list + Triage detail. Direction-level feedback only.
- **Final review (~14 days in):** all of §3, deliverables §6, formal acceptance against §7.

---

## Appendix · Page → API endpoint mapping

| Page | Endpoints |
|---|---|
| P-01 / P-02 | `GET /auth/login` (redirect) → `GET /auth/callback` |
| P-08 | `GET /styles`, `GET /triage/blocks?status=IN_PROGRESS`, `GET /triage/blocks?status=FINALIZED&limit=1`, `GET /categories` |
| P-09 | `GET /styles/{style_id}/categories`, `POST /styles/{style_id}/categories`, `PUT /styles/{style_id}/categories/order`, `PATCH /categories/{id}`, `DELETE /categories/{id}` |
| P-10 | `GET /categories/{id}/tracks`, `DELETE /categories/{id}/tracks/{track_id}` |
| P-14 | `GET /triage/blocks`, `GET /styles/{style_id}/triage/blocks` |
| P-15 | `POST /triage/blocks`, `GET /styles/{style_id}/triage/blocks?status=IN_PROGRESS` (overlap detection) |
| P-16 | `GET /triage/blocks/{id}`, `DELETE /triage/blocks/{id}` |
| P-17 | `GET /triage/blocks/{id}/buckets/{bucket_id}/tracks` |
| P-18 | `POST /triage/blocks/{id}/move` |
| P-19 | `POST /triage/blocks/{src_id}/transfer` |
| P-20 / P-21 | `POST /triage/blocks/{id}/finalize`, `POST /triage/blocks/{id}/move` (P-21 bulk "Move all to DISCARD") |
| P-22 / P-23 / P-24 | `POST /categories/{id}/tracks` (single tap), `POST /triage/blocks/{id}/move` (intra-block tap) |
| P-25 | Spotify Web Playback SDK only (no CLOUDER endpoint) |

iter-2b page → endpoint mapping is deferred to the iter-2b brief.
