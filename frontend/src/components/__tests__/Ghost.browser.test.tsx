import { Anchor, Button, Card, Group, MantineProvider, Stack, Text } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { Ghost, GhostScope } from '../Ghost';

function Block({ on, testId }: { on: boolean; testId: string }) {
  return (
    <GhostScope on={on}>
      <Card withBorder padding="md" data-testid={testId}>
        <Stack gap="xs">
          <Text size="xs">Static title</Text>
          <Group justify="space-between">
            <Text size="sm">Label</Text>
            <Ghost>
              <Text fz={32} lh={1}>
                1,234
              </Text>
            </Ghost>
          </Group>
          <Ghost>
            <Text size="sm">A caption long enough to wrap onto a second line in a narrow card</Text>
          </Ghost>
          <Ghost>
            <Anchor href="#" size="sm" mt={6}>
              View all
            </Anchor>
          </Ghost>
          <Group>
            <Ghost>
              <Button>Open block</Button>
            </Ghost>
          </Group>
        </Stack>
      </Card>
    </GhostScope>
  );
}

const box = (id: string) => screen.getByTestId(id).getBoundingClientRect();

test.each([180, 480])('a ghost block is exactly as tall as the loaded one at %ipx', (width) => {
  render(
    <MantineProvider>
      <div style={{ width }}>
        <Block on testId="ghost" />
        <Block on={false} testId="real" />
      </div>
    </MantineProvider>,
  );
  expect(box('ghost').height).toBe(box('real').height);
  expect(box('ghost').width).toBe(box('real').width);
});

test('a ghost hides its content under a bar and is inert', () => {
  render(
    <MantineProvider>
      <Block on testId="ghost" />
    </MantineProvider>,
  );
  const bar = screen.getByText('1,234').parentElement!;
  expect(bar).toHaveAttribute('data-visible', 'true');
  expect(getComputedStyle(bar, '::after').content).not.toBe('none');
  expect(screen.getByTestId('ghost').closest('[inert]')).not.toBeNull();
  expect(screen.getByText('Static title').parentElement).not.toHaveAttribute('data-visible');
});
