import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface Tag {
  id: string;
  name: string;
  color: string | null;
  created_at: string;
  updated_at: string;
}

interface ListTagsResponse {
  items: Tag[];
  total: number;
  limit: number;
  offset: number;
}

export const tagsKey = () => ['tags'] as const;

const PAGE_LIMIT = 200; // single fetch — vocabulary is small

export function useTags(): UseQueryResult<Tag[]> {
  return useQuery<Tag[]>({
    queryKey: tagsKey(),
    queryFn: async () => {
      const res = await api<ListTagsResponse>(
        `/tags?limit=${PAGE_LIMIT}&offset=0`,
      );
      return res.items;
    },
    staleTime: 60_000,
  });
}
