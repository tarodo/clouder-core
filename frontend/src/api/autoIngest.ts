import type { paths } from './schema';

export type AutoIngestState =
  paths['/admin/auto-ingest']['get']['responses'][200]['content']['application/json'];
export type AutoIngestSettingsBody =
  paths['/admin/auto-ingest']['put']['requestBody']['content']['application/json'];
