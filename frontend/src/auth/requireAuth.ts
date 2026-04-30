import { redirect, type LoaderFunction } from 'react-router';
import { getAuthSnapshot } from './AuthProvider';
import { bootstrapPromise } from './bootstrap';

export const requireAuth: LoaderFunction = async () => {
  await bootstrapPromise();
  const snap = getAuthSnapshot();
  if (snap.status === 'authenticated') return null;
  throw redirect('/login');
};

export const redirectIfAuthenticated: LoaderFunction = async () => {
  await bootstrapPromise();
  const snap = getAuthSnapshot();
  if (snap.status === 'authenticated') throw redirect('/');
  return null;
};
