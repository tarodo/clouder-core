import { describe, it, expect } from 'vitest';
import { router } from '../router';

interface RNode {
  path?: string;
  loader?: unknown;
  children?: RNode[];
}

function find(nodes: RNode[], path: string): RNode | undefined {
  for (const n of nodes) {
    if (n.path === path) return n;
    if (n.children) {
      const hit = find(n.children, path);
      if (hit) return hit;
    }
  }
  return undefined;
}

describe('/admin/analytics route', () => {
  it('is a child of the requireAdmin-gated admin subtree', () => {
    const admin = find(router.routes as RNode[], 'admin');
    expect(admin).toBeDefined();
    expect(admin?.loader).toBeTruthy(); // requireAdmin gate present (loader tested separately)
    const analytics = admin?.children?.find((c) => c.path === 'analytics');
    expect(analytics).toBeDefined();
  });
});
