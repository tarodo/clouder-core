import { Anchor, Paper, Text } from '@mantine/core';

/** Always-visible note that this is the sample-data demo, not the live app. */
export function DemoBanner() {
  return (
    <Paper
      withBorder
      shadow="sm"
      radius="xl"
      px="md"
      py={6}
      pos="fixed"
      bottom={12}
      left={12}
      style={{ zIndex: 1000 }}
    >
      <Text size="xs">
        <b>Demo</b> · sample data, changes stay in this tab · playback needs Spotify ·{' '}
        <Anchor
          href="https://github.com/tarodo/clouder-core"
          target="_blank"
          rel="noreferrer"
          size="xs"
        >
          source
        </Anchor>
      </Text>
    </Paper>
  );
}
