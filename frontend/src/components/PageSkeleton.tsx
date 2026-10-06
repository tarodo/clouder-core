import { Flex, Group, SimpleGrid, Skeleton, Stack } from '@mantine/core';

export interface PageSkeletonProps {
  /** Breadcrumbs line above the header (detail pages). */
  breadcrumbs?: boolean;
  /** 'title' = page title + actions row; 'hero' = cover + meta panel (playlist);
   * 'none' = rows only (a list loading inside an already-rendered page). */
  header?: 'title' | 'hero' | 'none';
  /** Desktop-only side panel left of the rows (category player, 442px). */
  aside?: boolean;
  rows?: number;
  rowHeight?: number;
  /** >1 lays the rows out as a card grid (1 column on phones). */
  cols?: number;
}

/** Gray pulsing page placeholder while the first query loads — same look as HomeSkeleton. */
export function PageSkeleton({
  breadcrumbs = false,
  header = 'title',
  aside = false,
  rows = 6,
  rowHeight = 52,
  cols = 1,
}: PageSkeletonProps) {
  const blocks = Array.from({ length: rows }, (_, i) => (
    <Skeleton key={i} height={rowHeight} radius="md" />
  ));
  return (
    <Stack gap="lg" data-testid="page-skeleton" aria-busy="true">
      {breadcrumbs && <Skeleton height={14} width={200} radius="sm" />}
      {header === 'hero' ? (
        <Group align="flex-start" wrap="nowrap" gap="md">
          <Skeleton height={120} width={120} radius="md" style={{ flexShrink: 0 }} />
          <Stack gap="xs" style={{ flex: 1, minWidth: 0 }}>
            <Skeleton height={32} width="60%" radius="sm" />
            <Skeleton height={14} width="80%" radius="sm" />
            <Skeleton height={36} width="45%" radius="sm" />
          </Stack>
        </Group>
      ) : header === 'title' ? (
        <Group justify="space-between" wrap="nowrap" gap="md">
          <Skeleton height={36} width={220} radius="sm" />
          <Skeleton height={36} width={240} radius="sm" visibleFrom="sm" />
        </Group>
      ) : null}
      <Flex gap="lg" align="flex-start" wrap="nowrap">
        {aside && <Skeleton height={420} width={442} radius="md" visibleFrom="md" style={{ flexShrink: 0 }} />}
        {cols > 1 ? (
          <SimpleGrid cols={{ base: 1, sm: cols }} spacing="sm" style={{ flex: 1, minWidth: 0 }}>
            {blocks}
          </SimpleGrid>
        ) : (
          <Stack gap="xs" style={{ flex: 1, minWidth: 0 }}>
            {blocks}
          </Stack>
        )}
      </Flex>
    </Stack>
  );
}
