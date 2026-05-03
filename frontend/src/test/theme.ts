import type { MantineThemeOverride } from '@mantine/core';

/**
 * Test-only Mantine theme: disables Modal animation to avoid jsdom
 * portal-transition races. Apply via `<MantineProvider theme={testTheme}>`
 * in test render helpers.
 */
export const testTheme: MantineThemeOverride = {
  components: {
    Modal: {
      defaultProps: {
        transitionProps: { duration: 0 },
      },
    },
  },
};
