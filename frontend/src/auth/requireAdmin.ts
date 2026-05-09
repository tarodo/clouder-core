import { redirect, type LoaderFunction } from 'react-router';
import { getAuthSnapshot } from './AuthProvider';
import { bootstrapPromise } from './bootstrap';

export const requireAdmin: LoaderFunction = async () => {
  await bootstrapPromise();
  const snap = getAuthSnapshot();
  if (snap.status !== 'authenticated') throw redirect('/');
  if (!snap.user.is_admin) throw redirect('/');
  return null;
};
