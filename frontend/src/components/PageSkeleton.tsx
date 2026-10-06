import { Flex, Group, Skeleton, Stack } from '@mantine/core';

export interface PageSkeletonProps {
  /** Breadcrumbs line above the header (detail pages). */
  breadcrumbs?: boolean;
  /** 'title' = page title + actions row; 'hero' = cover + meta panel (playlist). */
  header?: 'title' | 'hero';
  /** Desktop-only side panel left of the rows (category player, 442px). */
  aside?: boolean;
  rows?: number;
  rowHeight?: number;
}

/** Gray pulsing page placeholder while the first query loads — same look as HomeSkeleton. */
export function PageSkeleton({
  breadcrumbs = false,
  header = 'title',
  aside = false,
  rows = 6,
  rowHeight = 52,
}: PageSkeletonProps) {
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
      ) : (
        <Group justify="space-between" wrap="nowrap" gap="md">
          <Skeleton height={36} width={220} radius="sm" />
          <Skeleton height={36} width={240} radius="sm" visibleFrom="sm" />
        </Group>
      )}
      <Flex gap="lg" align="flex-start" wrap="nowrap">
        {aside && <Skeleton height={420} width={442} radius="md" visibleFrom="md" style={{ flexShrink: 0 }} />}
        <Stack gap="xs" style={{ flex: 1, minWidth: 0 }}>
          {Array.from({ length: rows }, (_, i) => (
            <Skeleton key={i} height={rowHeight} radius="md" />
          ))}
        </Stack>
      </Flex>
    </Stack>
  );
}
