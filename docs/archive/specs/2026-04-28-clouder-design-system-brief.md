# CLOUDER · Design System Brief

> Brief for an external designer. Output: a reusable design system ready to be imported into a React + Tailwind v4 codebase.

**Date:** 2026-04-28
**Owner:** Roman (product author / engineer)
**Audience for this brief:** UI/UX designer hired to build the system

---

## 1. Product Context

**CLOUDER** is a tool for DJs that collects new releases from Beatport, enriches them with Spotify metadata, and helps the DJ rapidly *curate* tracks (sort them into personal categories and playlists) on both desktop and mobile. It is not a public SaaS — it is a niche tool for the author and a small circle of DJ friends.

### The core pain CLOUDER solves

A DJ receives hundreds of new releases every week. Listening through them, deciding "in / out / where to file" by hand against Spotify playlists does not scale. CLOUDER shortens this loop.

### Main workflow (one cycle = one week of releases)

1. **Collection** — admin triggers `import` for a style and ISO week. The system pulls Beatport, stores raw snapshots, and enriches with Spotify (ISRC, BPM, key, cover art). A "raw block" of tracks is ready to listen to.
2. **Triage** — DJ opens the Player. Audio is streamed by the Spotify app on their device; CLOUDER drives controls and metadata via the Spotify Web API. The DJ listens for 30–60 seconds, then with a *single tap* sends the track to one of their categories ("Peak Hour", "Warm-Up", "Deep Cuts") or to "Discard".
3. **Categories management** — DJ creates and renames categories inside a style (House, Techno…). Categories are personal buckets, not shared.
4. **Playlists view** — overview of accumulated work: raw layer, by category, by release, plus regular Spotify user playlists.
5. **Finalize** — the session closes; tracks move from staging into permanent playlists.

### Key user-facing entities

- **Track** — title, artist(s), BPM, key (1A–12B Camelot notation), duration, cover art.
- **Category** — user-defined bucket inside a style (name, order).
- **Style** — genre (House, Techno…), selected from the top of the UI.
- **Bucket** — within a triage session: `NEW` / `OLD` / `NOT` / `DISCARD` / `STAGING`.
- **Block** — a weekly session for one style; it contains buckets.
- **Playlist** — a Spotify playlist linked to a category or release.

### The most important interaction — *triage tap*

> Hear a track → one tap on a category / playlist name → the track is filed there → next track.

This is the **heart** of the product. It must work equally fast on desktop (mouse + keyboard hotkeys — digits for destination buttons, plus `Space` / arrows for transport and seek) and on a phone (one-handed thumb use).

**No drag-and-drop.** Curation is performed exclusively by tapping buttons that show destination names. This is a deliberate decision in service of mobile speed and predictability.

### Platforms and auth

- **Web only** (responsive). No native mobile app.
- **Auth:** Spotify OAuth. A Spotify Premium account is required (audio is played by Spotify; metadata comes from Spotify Web API).

---

## 2. Tech Context

The designer does not write code, but the following constrains how tokens and components are delivered:

- **Frontend stack:** React + TypeScript, Vite. Styling via Tailwind v4 + CSS custom properties. Base components: shadcn/ui (Radix-based) — they handle a11y primitives out of the box.
- **Token format:**
  - CSS custom properties: `--color-bg`, `--color-fg`, `--radius-md`, `--space-4`, `--font-sans`, `--font-mono`, etc.
  - Color values in `oklch(...)` (perceptual uniformity, mix-friendly), **not hex**.
  - Light + dark are equal first-class themes; not "light is default, dark is for power users".
  - Mapping must be 1-to-1 compatible with Tailwind v4 `@theme` block.
- **Responsive strategy:** mobile-first. Standard Tailwind breakpoints: `sm 640`, `md 768`, `lg 1024`, `xl 1280`. Primary targets — mobile 360–430px (iPhone Pro / Android), desktop 1280–1440px.
- **Fonts:** open-source or system fonts only. No commercial licenses. Two families required:
  - **Sans** for UI text.
  - **Mono** for tabular numerics (BPM, key, duration, IDs, hex values).

---

## 3. Design Direction

### Mood

**Studio Mono** — minimalist, monochrome, dense "pro tool". Reference points: Linear, Vercel dashboard, shadcn/ui defaults, Ableton-inspired DJ utility surfaces.

### Aesthetic principles

- **Base palette:** monochrome `oklch` grayscale.
  - Light: `#fff` background → near-black `#0a0a0a` text.
  - Dark: `#0a0a0a` → `#fafafa`.
  - 6–8 neutral steps between the extremes.
- **Accent:** *by default — no bright accent.* Selected / active states are expressed by inversion (foreground fill, background text). The designer **may** propose a single accent token (e.g. magenta, electric blue, acid lime) **if** they can argue that critical UX signals (Now Playing, selected destination) are lost without it. Default ship is mono.
- **Border radii:** four steps — `xs 4px`, `sm 6px`, `md 10px`, `lg 14px`. No soft-blob radii (24px+).
- **Shadows:** minimal. `sm` only for popovers / dropdowns, `md` only for modals. Otherwise hierarchy is carried by `border` and color steps.
- **Density:** comfortable, not cramped.
  - Default button height: 36–40px on desktop, ≥44px on mobile (touch target spec).
- **Typography:**
  - **Sans:** clean, neutral, geometric grotesque (Inter / Geist / IBM Plex Sans — designer's choice). No variable-font tricks in the base scale.
  - **Mono:** for tabular numerics (BPM, key, time, IDs). Designer's choice (JetBrains Mono / Geist Mono / IBM Plex Mono).
  - **Scale:** `11 / 12 / 13 / 14 / 16 / 18 / 24 / 32`. Each size carries its own line-height and weight token.
  - **Tracking:** `+0.01em..+0.05em` for 11–13px (readability on dense UI). `−0.01em..−0.02em` for 24px+ display.
- **Iconography:** one linear icon set (Lucide / Phosphor / Heroicons-outline). Stroke 1.5–2px. Sizes 16 / 20 / 24.
- **Motion:** restrained. Transitions 120–200ms `ease-out`. No parallax, springs, or morphs. Two intentional exceptions:
  1. Track change in Player — subtle fade.
  2. Tap on a destination button — haptic-like 80ms scale pulse to confirm action.

### Brand mark

- **Wordmark "CLOUDER"** — designer creates a fresh wordmark. Display weight may differ from UI sans. **The existing `cLouder.svg` (cloud-with-face mark) is NOT to be reused as a production mark.**
- **Icon (favicon / app mark)** — simple, geometric. Designer presents 2–3 options.

### Inherit from the existing frontend (mood reference only, not a constraint)

- Pill-tab idea (compact segmented navigation).
- Density of information in tables (TrackRow with tabular numerics).
- Card components driven by thin borders, not heavy shadows.
- Color minimalism.

### Avoid

- Generic "shadcn-default" look without character (CLOUDER must not look like another admin template).
- Pastel palettes, gradient backgrounds, glassmorphism.
- Illustrations, mascots, emoji in UI.

---

## 4. Component Library

The designer delivers **two layers**: base components (atoms) and product components (CLOUDER-specific patterns).

### 4.1 Base Components

Each component must include all relevant states (`default` / `hover` / `focus` / `active` / `disabled` / `loading` where applicable), sizes (`sm` / `md` / `lg`), and both themes.

| Component | Variants / States | Notes |
|---|---|---|
| **Button** | `primary` / `secondary` / `ghost` / `outline` / `destructive` · sm/md/lg · with/without icon · icon-only | Mobile tap target ≥44px |
| **Input** | text / search / password · default/error/disabled · with/without leading icon · with/without `clear` action | Mono font for numeric fields |
| **Textarea** | default/error/disabled | |
| **Select / Dropdown** | single, with search inside (combobox) | Used for Style picker |
| **Checkbox** | unchecked / checked / indeterminate | |
| **Radio** | unchecked / checked | |
| **Switch** | on / off | Theme toggle, settings |
| **Tabs** | underline + pill variants · horizontal scrollable | Pill is primary (legacy reference) |
| **Card** | default · interactive (clickable) · with header / footer | Border-driven, not shadow-driven |
| **Badge / Tag** | neutral / outline / dot · sm/md | Used for BPM, key, status |
| **Table** | regular · compact · sticky header · row hover | TrackList, ReleasePlaylist |
| **List item** | default · selected · with leading / trailing slots | |
| **Skeleton** | bar / circle / text-line | Loading states |
| **Toast** | default / success / error / warning | Top-right desktop, top mobile |
| **Dialog / Modal** | default · sm/md/lg · alert-dialog (destructive confirm) | |
| **Sheet** | side (right desktop) / bottom (mobile) | Filter panels, mobile menu |
| **Popover** | default | |
| **Tooltip** | default · keyboard-shortcut variant | Hotkey hints |
| **Progress** | linear (player progress) · circular (loading) | Linear is critical for Player |
| **Avatar** | image / initials fallback · sm/md/lg | User profile |
| **Empty state** | text + icon + action button | Variants: no data / no results / error |
| **Separator** | horizontal / vertical | |
| **Breadcrumb** | default | Triage block detail |

### 4.2 Product Components

These are CLOUDER-specific. Without them the system is a generic admin template.

| Component | Description |
|---|---|
| **TrackRow** | Track line: title (bold) + artists (muted) + BPM (mono) + key (mono badge) + duration (mono) + trailing actions (like, send-to). Compact and regular density. Selectable. On mobile: title + artists in two lines, BPM/key/duration on a third line as inline mono meta. |
| **DestinationButton** ⭐ | The core curation button. Large touch target showing a category / playlist name. States: `idle`, `hover`, `primary` (recommended target), `just-tapped` (200ms confirmation pulse), `disabled`. Mobile-first. Supports a hotkey hint badge in the corner (`1`–`9`). |
| **PlayerCard** | Now Playing: cover (square 80–120px) + title + artists + BPM/key (mono) + progress bar + transport controls (`prev` / `play` / `next` / `seek`). Adapts to a compact mini-player (sticky bottom on mobile). |
| **NowPlayingDot** | Small "currently playing" indicator next to a TrackRow / inside playlists. Animated pulse. |
| **CategoryPill** | Category name + reorder handles (`↑` / `↓` buttons, **not drag**) + edit pencil. Compact. |
| **StyleSelector** | Top-bar style picker (House, Techno…). Segmented control on desktop, dropdown on mobile. |
| **TriageBucket** | Container for one bucket (`NEW` / `OLD` / `DISCARD`) inside a block. Header with counter + list of TrackRow + footer actions (move all, finalize). |
| **BlockHeader** | Session metadata: style + week + date range + per-bucket counters + finalize CTA. |
| **CollectionStat** | Metric card: number + label + delta (e.g. `1,247 tracks · +56 this week`). Mono numerics. |
| **HotkeyHint** | Small mono badge displaying a key (`>`, `1`, `Space`). Inline or absolutely positioned on a component. |
| **AppShell** | Main layout frame: top bar (CLOUDER wordmark + nav + theme toggle + user avatar), content area, mobile bottom tab bar (`Player` / `Curate` / `Playlists`). |

---

## 5. Anchor Scene

Instead of full-screen designs, the designer composes **one anchor scenario** that proves the components work in a real flow. The designer must keep the full product (Section 1) in mind while building the system, but is **not** required to design every screen in this sprint.

| # | Scene | Purpose |
|---|---|---|
| **5.1** | **Player + Curate, mobile** ⭐ | The heart of the product. One frame: top bar with CLOUDER, compact track info (cover / title / BPM / key), player controls, grid of DestinationButtons, Discard button at the bottom. Proves the system covers the main interaction. |
| **5.2** *(optional)* | **Player + Curate, desktop** | Same scenario in a 1440px desktop frame, including hotkey hints. Welcome but not required. |

Anything else (Login, Triage Block detail, Categories, Collection, Playlists overview) is **the next iteration**, after the system is approved.

### What the designer does in this sprint

1. **Tokens** — colors, type scale, radii, spacing, shadows, motion.
2. **Base components** (Section 4.1) — all states, both themes.
3. **Product components** (Section 4.2) — all states, both themes.
4. **Anchor scene** (5.1, optionally 5.2) — built from library components, validating the system on the main flow.

### What the designer does NOT do

- Full design of all screens (next iteration).
- Wireframes / user flows / IA — the product is already designed, see Section 1.
- Marketing / landing.
- Illustrations.

---

## 6. Deliverables & Acceptance

### 6.1 What to deliver

The designer works in **whichever tool fits them**: Figma, Sketch, Penpot, code-based (Storybook + CSS), Framer, etc. The tool is not prescribed — what *is* prescribed is what the system must contain.

Required artifacts (the designer chooses the format for each):

1. **Design system source — file or repository**
   - Live access (Figma share / Penpot URL / Storybook deploy / repo with CSS + HTML).
   - Structure: `Foundations` (tokens) · `Base Components` · `Product Components` · `Anchor Scene` · `Mood / References`.
   - Components are *reusable instances*, not duplicated frames (Figma Components / Sketch Symbols / Penpot Components / web component / CSS class).

2. **Tokens — machine-readable export**
   - **JSON** in [W3C Design Tokens](https://www.designtokens.org/) format or Style-Dictionary-compatible.
   - **CSS** (`tokens.css`): `:root { ... }` for light, `.dark { ... }` for dark. Compatible with Tailwind v4 `@theme`.
   - Colors in `oklch(...)`, not hex.
   - Groups: `color`, `font`, `space`, `radius`, `shadow`, `motion`.

3. **Components catalog — viewable inventory**
   - One of: a published library, a deployed Storybook, a static HTML/PDF catalog, a Figma document with a public link.
   - Each component shows all states / sizes / themes on a single screen.

4. **Brand assets**
   - Wordmark CLOUDER: SVG (master), 2–3 variants on offer.
   - Icon (favicon / app mark): SVG + PNG (16 / 32 / 180 / 512).

5. **README / Designer notes** (markdown)
   - What the system contains, how to import / use it.
   - Token naming conventions.
   - Principles (when to use which component, when to step outside the system).
   - If an accent token is proposed — written rationale here.

### 6.2 Acceptance criteria

| # | Criterion |
|---|---|
| **A1** | Tokens are defined for both light and dark; no hardcoded colors / sizes inside components — only token references |
| **A2** | Each component has `default` / `hover` / `focus` / `active` / `disabled` states where applicable |
| **A3** | Components are *reusable instances*, not duplicated frames — editing one place updates all instances |
| **A4** | Mobile tap targets ≥44pt on all interactive components |
| **A5** | Contrast meets WCAG AA: ≥4.5:1 for body text, ≥3:1 for large text and UI controls — in both themes |
| **A6** | Tokens export to `tokens.css` and work inside Tailwind v4 with no manual editing |
| **A7** | The anchor scene is composed *from library components*, not hand-drawn |
| **A8** | The CLOUDER wordmark remains legible at 14px without losing form |
| **A9** | Sans + mono fonts are open-source or system fonts |
| **A10** | The components catalog is reachable by URL or file for review without installing niche software |

### 6.3 Process

- **Kickoff call** (~30 min) — walk the brief together, agree on tool, agree on a mid-point check.
- **Tool decision** — after kickoff, the designer states which tool they will use. Confirmed by owner unless there is a technical blocker.
- **Mid-point review** (~1 week in) — foundations + ~30% of components. Direction-level feedback only.
- **Final review** — formal acceptance against §6.2.

### 6.4 Bake-in for the future

The system must be **ready to extend**, not finalized to the current scope:

- Token naming permits adding an accent palette later without migration.
- The component set extends through variants, not by adding new components — e.g. `TrackRow` will later gain a `with-waveform` variant.
- Theme architecture allows adding a third theme later (e.g. high-contrast, or a "mono mode" if the accent route is taken).

---

## 7. Out of Scope

To save the designer's time:

- **Full design of remaining screens** (Login, Triage block detail, Categories, Collection, Playlists detail, Settings) — next iteration.
- **Marketing / landing page**, public website, app-store screenshots.
- **Illustrations, mascot, emoji, stickers, animations beyond UI motion.**
- **User flows / wireframes / IA** — the product is already designed (Section 1).
- **Detailed motion / animation spec** (Lottie, AfterEffects). Only baseline: transition timings + easings as tokens.
- **Email templates, push notifications, error pages** (404 / 500).
- **Native mobile app design** (iOS / Android specifics) — product is web-only.
- **Accessibility audit beyond WCAG AA contrast** — screen-reader and focus-management patterns are handled by shadcn/ui in code.
- **Code / dev handoff** — designer ships the system + tokens; the engineer translates to code.

---

## Appendix A · Glossary

| Term | Meaning |
|---|---|
| **Style** | A music genre selected at the top of the app (House, Techno, Drum & Bass…). |
| **Category** | A user-defined bucket inside a style (e.g. "Peak Hour"). |
| **Block** | A weekly triage session for one style; contains buckets. |
| **Bucket** | A staging container inside a block: `NEW`, `OLD`, `NOT`, `DISCARD`, `STAGING`. |
| **Triage** | The act of listening to tracks and sending them to destinations. |
| **Curation** | The broader workflow that includes triage + organising categories + finalising playlists. |
| **Camelot key** | DJ-friendly notation for musical key (`1A`–`12B`). Always rendered in mono font. |

## Appendix B · References (mood)

- Linear — overall density, type, monochrome restraint
- Vercel dashboard — tabular data, mono numerics
- shadcn/ui — base component vocabulary (the floor, not the ceiling)
- Ableton Live — pro-tool density, dark theme as a working surface
- Beatport — domain familiarity (DJs already know this UI)
- Sonos S2 — hi-fi calm, restrained motion

## Appendix C · The existing frontend

The current frontend lives in `repomix-output.xml` at the project root. It is a **mood reference only**: monochrome `oklch` palette, pill-tab nav, dashed-border cards, shadcn/ui defaults. The new system is free to break with it on density, type, components, and stack — it is not a constraint, just a starting point that the owner found "honest but unfinished".
