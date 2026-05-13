const CURATE_SESSION = /^\/curate\/[^/]+\/([^/]+)\/([^/]+)\/?$/;
const CATEGORY_DETAIL = /^\/categories\/([^/]+)\/([^/]+)\/?$/;

export function hasPlayerCard(pathname: string): boolean {
  return CURATE_SESSION.test(pathname) || CATEGORY_DETAIL.test(pathname);
}

export type RouteContext =
  | { type: 'bucket'; blockId: string; bucketId: string }
  | { type: 'category'; styleId: string; categoryId: string };

export function contextOf(pathname: string): RouteContext | null {
  const curate = CURATE_SESSION.exec(pathname);
  if (curate) {
    const [, blockId, bucketId] = curate;
    if (blockId === undefined || bucketId === undefined) return null;
    return { type: 'bucket', blockId, bucketId };
  }
  const category = CATEGORY_DETAIL.exec(pathname);
  if (category) {
    const [, styleId, categoryId] = category;
    if (styleId === undefined || categoryId === undefined) return null;
    return { type: 'category', styleId, categoryId };
  }
  return null;
}

export function contextDifferent(currentPath: string, nextPath: string): boolean {
  const a = contextOf(currentPath);
  const b = contextOf(nextPath);
  if (!a || !b) return false;
  if (a.type !== b.type) return true;
  if (a.type === 'bucket' && b.type === 'bucket') {
    return a.blockId !== b.blockId || a.bucketId !== b.bucketId;
  }
  if (a.type === 'category' && b.type === 'category') {
    return a.styleId !== b.styleId || a.categoryId !== b.categoryId;
  }
  return false;
}
