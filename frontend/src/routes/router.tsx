import { createBrowserRouter } from 'react-router';
import { Navigate } from 'react-router';
import { AppShellLayout } from './_layout';
import { LoginPage } from './login';
import { AuthReturnPage } from './auth.return';
import { HomePage } from '../features/home/routes/HomePage';
import { CategoriesIndexRedirect } from '../features/categories/routes/CategoriesIndexRedirect';
import { CategoriesListPage } from '../features/categories/routes/CategoriesListPage';
import { CategoryDetailPage } from '../features/categories/routes/CategoryDetailPage';
import { CategoryPlayerPage } from '../features/categories/routes/CategoryPlayerPage';
import { TriageIndexRedirect } from '../features/triage/routes/TriageIndexRedirect';
import { TriageListPage } from '../features/triage/routes/TriageListPage';
import { TriageDetailPage } from '../features/triage/routes/TriageDetailPage';
import { BucketDetailPage } from '../features/triage/routes/BucketDetailPage';
import { BucketPlayerPage } from '../features/triage/routes/BucketPlayerPage';
import {
  CurateIndexRedirect,
  CurateStyleResume,
  CurateSessionPage,
} from '../features/curate';
import { PlaylistsListPage } from '../features/playlists/routes/PlaylistsListPage';
import { PlaylistDetailPage } from '../features/playlists/routes/PlaylistDetailPage';
import { PlaylistPlayerPage } from '../features/playlists/routes/PlaylistPlayerPage';
import { ProfilePage } from './profile';
import { NotFoundPage } from './not-found';
import { RouteErrorBoundary } from '../components/RouteErrorBoundary';
import { requireAuth, redirectIfAuthenticated } from '../auth/requireAuth';
import { requireAdmin } from '../auth/requireAdmin';
import { AdminLayout } from '../features/admin/routes/AdminLayout';
import { AdminCoveragePage } from '../features/admin/routes/AdminCoveragePage';
import { AdminSpotifyNotFoundPage } from '../features/admin/routes/AdminSpotifyNotFoundPage';
import { AdminEnrichmentBacklogPage } from '../features/admin/routes/AdminEnrichmentBacklogPage';
import { AdminEnrichmentRunsPage } from '../features/admin/routes/AdminEnrichmentRunsPage';
import { AdminEnrichmentRunDetailPage } from '../features/admin/routes/AdminEnrichmentRunDetailPage';
import { AdminAutoEnrichPage } from '../features/admin/routes/AdminAutoEnrichPage';
import { AdminArtistEnrichmentBacklogPage } from '../features/admin/routes/AdminArtistEnrichmentBacklogPage';
import { AdminArtistEnrichmentRunsPage } from '../features/admin/routes/AdminArtistEnrichmentRunsPage';
import { AdminArtistEnrichmentRunDetailPage } from '../features/admin/routes/AdminArtistEnrichmentRunDetailPage';
import { LibraryIndexRedirect, LibraryListPage, ArtistsListPage, LabelDetailPage, ArtistDetailPage } from '../features/library';

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
    loader: redirectIfAuthenticated,
    errorElement: <RouteErrorBoundary />,
  },
  {
    path: '/auth/return',
    element: <AuthReturnPage />,
    errorElement: <RouteErrorBoundary />,
  },
  {
    element: <AppShellLayout />,
    loader: requireAuth,
    errorElement: <RouteErrorBoundary />,
    children: [
      { index: true, element: <HomePage /> },
      {
        path: 'categories',
        children: [
          { index: true, element: <CategoriesIndexRedirect /> },
          { path: ':styleId', element: <CategoriesListPage /> },
          {
            path: ':styleId/:id',
            element: <CategoryDetailPage />,
            children: [
              { path: 'player', element: <CategoryPlayerPage /> },
            ],
          },
        ],
      },
      {
        path: 'triage',
        children: [
          { index: true, element: <TriageIndexRedirect /> },
          { path: ':styleId', element: <TriageListPage /> },
          { path: ':styleId/:id', element: <TriageDetailPage /> },
          {
            path: ':styleId/:id/buckets/:bucketId',
            element: <BucketDetailPage />,
            children: [{ path: 'player', element: <BucketPlayerPage /> }],
          },
        ],
      },
      {
        path: 'curate',
        children: [
          { index: true, element: <CurateIndexRedirect /> },
          { path: ':styleId', element: <CurateStyleResume /> },
          { path: ':styleId/:blockId/:bucketId', element: <CurateSessionPage /> },
        ],
      },
      {
        path: 'library',
        children: [
          { index: true, element: <LibraryIndexRedirect /> },
          { path: ':styleId', element: <LibraryListPage /> },
          { path: ':styleId/labels/:labelId', element: <LabelDetailPage /> },
          { path: ':styleId/artists', element: <ArtistsListPage /> },
          { path: ':styleId/artists/:artistId', element: <ArtistDetailPage /> },
        ],
      },
      {
        path: 'playlists',
        children: [
          { index: true, element: <PlaylistsListPage /> },
          {
            path: ':id',
            element: <PlaylistDetailPage />,
            children: [{ path: 'player', element: <PlaylistPlayerPage /> }],
          },
        ],
      },
      { path: 'profile', element: <ProfilePage /> },
      {
        path: 'admin',
        element: <AdminLayout />,
        loader: requireAdmin,
        children: [
          { index: true, element: <Navigate to="/admin/coverage" replace /> },
          { path: 'coverage', element: <AdminCoveragePage /> },
          { path: 'spotify-not-found', element: <AdminSpotifyNotFoundPage /> },
          { path: 'labels/enrich', element: <AdminEnrichmentBacklogPage /> },
          { path: 'labels/enrich/runs', element: <AdminEnrichmentRunsPage /> },
          { path: 'labels/enrich/runs/:runId', element: <AdminEnrichmentRunDetailPage /> },
          { path: 'artists/enrich', element: <AdminArtistEnrichmentBacklogPage /> },
          { path: 'artists/enrich/runs', element: <AdminArtistEnrichmentRunsPage /> },
          { path: 'artists/enrich/runs/:runId', element: <AdminArtistEnrichmentRunDetailPage /> },
          { path: 'auto-enrich', element: <AdminAutoEnrichPage /> },
        ],
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
]);
