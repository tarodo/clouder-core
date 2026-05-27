import type { paths } from './schema';

export type AutoEnrichConfigResponse =
  paths['/admin/auto-enrich/artists']['get']['responses'][200]['content']['application/json'];
export type AutoEnrichConfigBody =
  paths['/admin/auto-enrich/artists']['put']['requestBody']['content']['application/json'];
