import { Anchor, Group, PasswordInput, Text } from '@mantine/core';
import { bpTokenStore, useBpToken } from '../lib/bpTokenStore';

export function BpTokenInput() {
  const token = useBpToken();
  if (token) {
    return (
      <Group justify="space-between">
        <Text size="sm">Beatport token loaded</Text>
        <Anchor size="sm" component="button" type="button" onClick={() => bpTokenStore.clear()}>
          Reset
        </Anchor>
      </Group>
    );
  }
  return (
    <PasswordInput
      label="Beatport token"
      placeholder="Paste bp_token"
      onChange={(e) => bpTokenStore.set(e.currentTarget.value || null)}
      autoComplete="off"
      data-testid="bp-token-input"
    />
  );
}
