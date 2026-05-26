import type { paths } from './schema';

export type AutoEnrichConfigResponse =
  paths['/admin/auto-enrich/labels']['get']['responses'][200]['content']['application/json'];
export type AutoEnrichConfigBody =
  paths['/admin/auto-enrich/labels']['put']['requestBody']['content']['application/json'];
