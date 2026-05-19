import type { paths } from './schema';

export type LabelSummary       = paths['/labels']['get']['responses'][200]['content']['application/json']['items'][number];
export type LabelsListResponse = paths['/labels']['get']['responses'][200]['content']['application/json'];
export type LabelDetail        = paths['/labels/{label_id}']['get']['responses'][200]['content']['application/json'];
export type BacklogLabel       = paths['/admin/labels/backlog']['get']['responses'][200]['content']['application/json']['items'][number];
export type BacklogResponse    = paths['/admin/labels/backlog']['get']['responses'][200]['content']['application/json'];
export type RunSummary         = paths['/admin/labels/enrich-runs']['get']['responses'][200]['content']['application/json']['items'][number];
export type RunsListResponse   = paths['/admin/labels/enrich-runs']['get']['responses'][200]['content']['application/json'];
export type RunDetail          = paths['/admin/labels/enrich-runs/{run_id}']['get']['responses'][200]['content']['application/json'];
export type RunCell            = NonNullable<RunDetail['cells']>[number];
export type EnrichmentOptions  = paths['/admin/labels/enrich/options']['get']['responses'][200]['content']['application/json'];
export type EnrichBody         = paths['/admin/labels/enrich']['post']['requestBody']['content']['application/json'];
