import { createBrowserRouter } from 'react-router';
import { AppShellLayout } from './_layout';
import { LoginPage } from './login';
import { AuthReturnPage } from './auth.return';
import { HomePage } from './home';
import { CategoriesIndexRedirect } from '../features/categories/routes/CategoriesIndexRedirect';
import { CategoriesListPage } from '../features/categories/routes/CategoriesListPage';
import { CategoryDetailPage } from '../features/categories/routes/CategoryDetailPage';
import { TriagePage } from './triage';
import { CuratePage } from './curate';
import { ProfilePage } from './profile';
import { NotFoundPage } from './not-found';
import { RouteErrorBoundary } from '../components/RouteErrorBoundary';
import { requireAuth, redirectIfAuthenticated } from '../auth/requireAuth';

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
      { path: 'triage', element: <TriagePage /> },
      { path: 'curate', element: <CuratePage /> },
      { path: 'profile', element: <ProfilePage /> },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
]);
