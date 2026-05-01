import { Center, Loader, Stack, Text } from '@mantine/core';

export function FullScreenLoader({ copy }: { copy?: string }) {
  return (
    <Center mih="100vh">
      <Stack align="center" gap="md">
        <Loader size="md" />
        {copy && <Text c="dimmed">{copy}</Text>}
      </Stack>
    </Center>
  );
}
