const CURATE_SESSION = /^\/curate\/[^/]+\/([^/]+)\/([^/]+)\/?$/;

export function hasPlayerCard(pathname: string): boolean {
  return CURATE_SESSION.test(pathname);
}

export type RouteContext = {
  type: 'bucket';
  blockId: string;
  bucketId: string;
};

export function contextOf(pathname: string): RouteContext | null {
  const match = CURATE_SESSION.exec(pathname);
  if (!match) return null;
  const [, blockId, bucketId] = match;
  if (blockId === undefined || bucketId === undefined) return null;
  return { type: 'bucket', blockId, bucketId };
}

export function contextDifferent(
  currentPath: string,
  nextPath: string,
): boolean {
  const a = contextOf(currentPath);
  const b = contextOf(nextPath);
  if (!a || !b) return false;
  return a.blockId !== b.blockId || a.bucketId !== b.bucketId;
}
