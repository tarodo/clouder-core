import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface AdminUser {
  id: string;
  display_name: string | null;
}

export function useUsers() {
  return useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => api<{ users: AdminUser[] }>('/admin/users'),
    staleTime: 300_000,
  });
}
