import { createBrowserRouter } from 'react-router';
import { Navigate } from 'react-router';
import { AppShellLayout } from './_layout';
import { LoginPage } from './login';
import { AuthReturnPage } from './auth.return';
import { HomePage } from '../features/home/routes/HomePage';
import { CategoriesIndexRedirect } from '../features/categories/routes/CategoriesIndexRedirect';
import { CategoriesListPage } from '../features/categories/routes/CategoriesListPage';
import { CategoryDetailPage } from '../features/categories/routes/CategoryDetailPage';
import { TriageIndexRedirect } from '../features/triage/routes/TriageIndexRedirect';
import { TriageListPage } from '../features/triage/routes/TriageListPage';
import { TriageDetailPage } from '../features/triage/routes/TriageDetailPage';
import { BucketDetailPage } from '../features/triage/routes/BucketDetailPage';
import {
  CurateIndexRedirect,
  CurateStyleResume,
  CurateSessionPage,
} from '../features/curate';
import { ProfilePage } from './profile';
import { NotFoundPage } from './not-found';
import { RouteErrorBoundary } from '../components/RouteErrorBoundary';
import { requireAuth, redirectIfAuthenticated } from '../auth/requireAuth';
import { requireAdmin } from '../auth/requireAdmin';
import { AdminLayout } from '../features/admin/routes/AdminLayout';
import { AdminCoveragePage } from '../features/admin/routes/AdminCoveragePage';
import { AdminSpotifyNotFoundPage } from '../features/admin/routes/AdminSpotifyNotFoundPage';

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
          { path: ':styleId/:id', element: <CategoryDetailPage /> },
        ],
      },
      {
        path: 'triage',
        children: [
          { index: true, element: <TriageIndexRedirect /> },
          { path: ':styleId', element: <TriageListPage /> },
          { path: ':styleId/:id', element: <TriageDetailPage /> },
          { path: ':styleId/:id/buckets/:bucketId', element: <BucketDetailPage /> },
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
      { path: 'profile', element: <ProfilePage /> },
      {
        path: 'admin',
        element: <AdminLayout />,
        loader: requireAdmin,
        children: [
          { index: true, element: <Navigate to="/admin/coverage" replace /> },
          { path: 'coverage', element: <AdminCoveragePage /> },
          { path: 'spotify-not-found', element: <AdminSpotifyNotFoundPage /> },
        ],
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
]);
