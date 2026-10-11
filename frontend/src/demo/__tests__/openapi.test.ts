import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';
import { DemoDb } from '../db';
import { demoRoutes } from '../handlers';

it('test_demo_routes_exist_in_openapi', () => {
  const spec = readFileSync(resolve(__dirname, '../../../../docs/api/openapi.yaml'), 'utf8');
  const known = new Set<string>();
  let path = '';
  for (const line of spec.split('\n')) {
    const p = line.match(/^ {2}(\/\S*):\s*$/);
    if (p?.[1]) path = p[1].replace(/\{[^}]+\}/g, '{}');
    const m = line.match(/^ {4}(get|post|put|patch|delete):\s*$/);
    if (m?.[1] && path) known.add(`${m[1]} ${path}`);
  }
  const missing = demoRoutes(new DemoDb(), 'http://localhost')
    .map((r) => `${r.method} ${r.path.replace(/:[^/]+/g, '{}')}`)
    .filter((k) => !known.has(k));
  expect(missing).toEqual([]);
});
