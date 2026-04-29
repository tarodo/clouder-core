/**
 * CLOUDER · Mantine theme
 * ---------------------------------------------------------------
 * MantineProvider theme override that mirrors `tokens.css` exactly.
 *
 * Usage:
 *   import { MantineProvider, createTheme } from "@mantine/core";
 *   import { clouderTheme } from "./theme";
 *   <MantineProvider theme={clouderTheme} defaultColorScheme="light">…</MantineProvider>
 *
 * Pair with `tokens.css` (imported once at app root). Tokens are the
 * source of truth for raw values; this file is the Mantine projection
 * of those tokens — keep them in sync.
 *
 * Conventions:
 *   - Mantine `colors` keys ARE the neutral ramp (10 stops, light theme).
 *     Dark theme is emitted via `colorScheme="dark"` + a CSS layer that
 *     swaps the same `--neutral-*` custom properties (see tokens.css
 *     `.theme-dark`).
 *   - All component widgets read from CSS variables (`var(--color-fg)`,
 *     `var(--color-border)`…) instead of Mantine's color resolver, so
 *     dark/light/accent switches happen via the CSS root class, not
 *     via JS theme rebuilds.
 *   - The accent color (`magenta`) is OPT-IN. Default UI is monochrome.
 * ---------------------------------------------------------------
 */

import { createTheme, MantineColorsTuple, type MantineThemeOverride } from "@mantine/core";

// ── Neutral ramp (light theme oklch values, hex approximations) ──
// Hex values precomputed from the oklch source in tokens.css for
// consumers/tools that don't yet support oklch().
const neutral: MantineColorsTuple = [
  "#ffffff", // 0   — bg
  "#fafafa", // 50  — bg-subtle
  "#f4f4f4", // 100 — bg-muted / hover
  "#e8e8e8", // 200 — border / active
  "#d4d4d4", // 300 — border-strong
  "#a3a3a3", // 400 — fg-subtle
  "#737373", // 500 — fg-muted
  "#525252", // 600
  "#1f1f1f", // 700
  "#0a0a0a", // 900 — fg
];

// Optional accent. Apply via `<div class="accent-magenta">` at theme
// root, or by setting `theme.primaryColor = "magenta"` in a scoped
// MantineProvider.
const magenta: MantineColorsTuple = [
  "#fff0f9",
  "#ffd9ee",
  "#ffafdb",
  "#ff7fc4",
  "#f74fab",
  "#e62b91",
  "#c91d7a", // 6 — primary
  "#a01060",
  "#7a0848",
  "#4a002b",
];

const fontFamilySans  = '"Geist", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';
const fontFamilyMono  = '"Geist Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace';

export const clouderTheme: MantineThemeOverride = createTheme({
  /* ── Color ─────────────────────────────────────────────── */
  colors: { neutral, magenta },
  primaryColor: "neutral",
  primaryShade: { light: 9, dark: 0 }, // dark inverts the ramp
  white: "#ffffff",
  black: "#0a0a0a",

  /* ── Type ──────────────────────────────────────────────── */
  fontFamily: fontFamilySans,
  fontFamilyMonospace: fontFamilyMono,
  headings: {
    fontFamily: fontFamilySans,
    fontWeight: "600",
    sizes: {
      h1: { fontSize: "32px", lineHeight: "38px", fontWeight: "600" },
      h2: { fontSize: "24px", lineHeight: "30px", fontWeight: "600" },
      h3: { fontSize: "18px", lineHeight: "26px", fontWeight: "600" },
      h4: { fontSize: "16px", lineHeight: "24px", fontWeight: "600" },
      h5: { fontSize: "14px", lineHeight: "20px", fontWeight: "600" },
      h6: { fontSize: "12px", lineHeight: "16px", fontWeight: "600" },
    },
  },
  fontSizes: {
    xs: "11px",
    sm: "12px",
    md: "14px",
    lg: "16px",
    xl: "18px",
  },
  lineHeights: {
    xs: "14px",
    sm: "16px",
    md: "20px",
    lg: "24px",
    xl: "26px",
  },

  /* ── Spacing ──────────────────────────────────────────── */
  // Mantine spacing keys map to our token rail:
  // xs=4, sm=8, md=12, lg=16, xl=20. Larger steps available via
  // `theme.other.space` (see below) for layout work.
  spacing: {
    xs: "4px",
    sm: "8px",
    md: "12px",
    lg: "16px",
    xl: "20px",
  },

  /* ── Radius ───────────────────────────────────────────── */
  radius: {
    xs: "4px",
    sm: "6px",
    md: "10px",
    lg: "14px",
    xl: "999px",
  },
  defaultRadius: "md",

  /* ── Shadows ──────────────────────────────────────────── */
  shadows: {
    xs: "0 1px 2px -1px oklch(0 0 0 / 0.06)",
    sm: "0 2px 6px -2px oklch(0 0 0 / 0.10), 0 1px 2px -1px oklch(0 0 0 / 0.08)",
    md: "0 12px 32px -8px oklch(0 0 0 / 0.18), 0 4px 8px -4px oklch(0 0 0 / 0.10)",
    lg: "0 20px 48px -12px oklch(0 0 0 / 0.22), 0 8px 16px -8px oklch(0 0 0 / 0.12)",
    xl: "0 32px 64px -16px oklch(0 0 0 / 0.28), 0 16px 32px -16px oklch(0 0 0 / 0.16)",
  },

  /* ── Cursor ───────────────────────────────────────────── */
  cursorType: "pointer",

  /* ── Component defaults ───────────────────────────────── */
  components: {
    Button: {
      defaultProps: {
        radius: "md",
      },
      styles: {
        root: {
          fontWeight: 500,
          letterSpacing: "0.005em",
        },
      },
    },
    ActionIcon: {
      defaultProps: {
        radius: "sm",
        variant: "subtle",
      },
    },
    Input: {
      defaultProps: {
        radius: "sm",
      },
    },
    Modal: {
      defaultProps: {
        radius: "md",
        centered: true,
        overlayProps: { backgroundOpacity: 0.4, blur: 2 },
      },
    },
    Card: {
      defaultProps: {
        radius: "md",
        withBorder: true,
        padding: "md",
      },
    },
    Notification: {
      defaultProps: {
        radius: "sm",
        withBorder: true,
      },
    },
    Tabs: {
      defaultProps: {
        variant: "default",
      },
    },
  },

  /* ── Custom scale (read via theme.other) ──────────────── */
  // Mantine's spacing tops out at xl=20. The full token rail goes
  // up to space-20 = 80px for layout (page padding, gaps in lanes,
  // sticky bar offsets). Read via theme.other.space[N].
  other: {
    space: {
      0: "0px",
      1: "4px",
      2: "8px",
      3: "12px",
      4: "16px",
      5: "20px",
      6: "24px",
      8: "32px",
      10: "40px",
      12: "48px",
      16: "64px",
      20: "80px",
    },
    motion: {
      fast: "120ms",
      base: "160ms",
      slow: "200ms",
      pulse: "80ms",
      easeOut: "cubic-bezier(0.2, 0.7, 0.2, 1)",
      easeInOut: "cubic-bezier(0.5, 0, 0.2, 1)",
    },
    control: {
      sm: "28px",
      md: "36px",
      lg: "44px", // mobile primary hit target
      xl: "56px", // destination buttons
    },
    semantic: {
      // CSS variable names — use these in styled components rather
      // than hard-coding hex from `colors.neutral` so dark mode and
      // accent overrides flow through automatically.
      bg: "var(--color-bg)",
      bgSubtle: "var(--color-bg-subtle)",
      bgMuted: "var(--color-bg-muted)",
      bgElevated: "var(--color-bg-elevated)",
      fg: "var(--color-fg)",
      fgMuted: "var(--color-fg-muted)",
      fgSubtle: "var(--color-fg-subtle)",
      fgInverse: "var(--color-fg-inverse)",
      border: "var(--color-border)",
      borderStrong: "var(--color-border-strong)",
      borderFocus: "var(--color-border-focus)",
      hover: "var(--color-hover)",
      active: "var(--color-active)",
      selectedBg: "var(--color-selected-bg)",
      selectedFg: "var(--color-selected-fg)",
      success: "var(--color-success)",
      warning: "var(--color-warning)",
      danger: "var(--color-danger)",
      accent: "var(--color-accent)",
      accentFg: "var(--color-accent-fg)",
      accentSoft: "var(--color-accent-soft)",
    },
  },
});

/**
 * Type-safe accessor for `theme.other.semantic.*`. Use inside a
 * Mantine `styles` callback or `useMantineTheme()` hook:
 *
 *   const t = useMantineTheme();
 *   <Box style={{ color: t.other.semantic.fgMuted }}>
 */
export type ClouderTheme = typeof clouderTheme & {
  other: NonNullable<typeof clouderTheme.other>;
};

declare module "@mantine/core" {
  // Augment Mantine's MantineTheme so theme.other is strongly typed.
  // eslint-disable-next-line @typescript-eslint/no-empty-interface
  export interface MantineThemeOther {
    space: Record<number, string>;
    motion: {
      fast: string;
      base: string;
      slow: string;
      pulse: string;
      easeOut: string;
      easeInOut: string;
    };
    control: { sm: string; md: string; lg: string; xl: string };
    semantic: {
      bg: string; bgSubtle: string; bgMuted: string; bgElevated: string;
      fg: string; fgMuted: string; fgSubtle: string; fgInverse: string;
      border: string; borderStrong: string; borderFocus: string;
      hover: string; active: string; selectedBg: string; selectedFg: string;
      success: string; warning: string; danger: string;
      accent: string; accentFg: string; accentSoft: string;
    };
  }
}
