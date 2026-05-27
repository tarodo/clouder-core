import type { paths } from './schema';

export type ArtistSummary       = paths['/artists']['get']['responses'][200]['content']['application/json']['items'][number];
export type ArtistsListResponse = paths['/artists']['get']['responses'][200]['content']['application/json'];
export type ArtistDetail        = paths['/artists/{artist_id}']['get']['responses'][200]['content']['application/json'];
export type BacklogArtist       = paths['/admin/artists/backlog']['get']['responses'][200]['content']['application/json']['items'][number];
export type BacklogResponse     = paths['/admin/artists/backlog']['get']['responses'][200]['content']['application/json'];
export type RunSummary          = paths['/admin/artists/enrich-runs']['get']['responses'][200]['content']['application/json']['items'][number];
export type RunsListResponse    = paths['/admin/artists/enrich-runs']['get']['responses'][200]['content']['application/json'];
export type RunDetail           = paths['/admin/artists/enrich-runs/{run_id}']['get']['responses'][200]['content']['application/json'];
export type RunCell             = NonNullable<RunDetail['cells']>[number];
export type EnrichmentOptions   = paths['/admin/artists/enrich/options']['get']['responses'][200]['content']['application/json'];
export type EnrichBody          = paths['/admin/artists/enrich']['post']['requestBody']['content']['application/json'];
export type ArtistHistoryResponse = paths['/admin/artists/{artist_id}/history']['get']['responses'][200]['content']['application/json'];
export type ArtistHistoryCell   = ArtistHistoryResponse['items'][number];
