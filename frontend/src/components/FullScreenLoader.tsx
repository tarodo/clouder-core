import { Center, Skeleton, Stack, Text } from '@mantine/core';

/** Full-screen wait (sign-in return): a gray pulsing bar, no spinner. */
export function FullScreenLoader({ copy }: { copy?: string }) {
  return (
    <Center mih="100vh">
      <Stack align="center" gap="md" w={240} aria-busy="true">
        <Skeleton height={8} radius="xl" data-testid="fullscreen-skeleton" />
        {copy && <Text c="dimmed">{copy}</Text>}
      </Stack>
    </Center>
  );
}
