import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';

export function useSetStyleHidden() {
  const qc = useQueryClient();
  return useMutation<void, Error, { styleId: string; isHidden: boolean }>({
    mutationFn: ({ styleId, isHidden }) =>
      api<void>(`/admin/styles/${styleId}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_hidden: isHidden }),
      }),
    onSuccess: () => {
      // Hidden styles also drop out of every /styles picker.
      void qc.invalidateQueries({ queryKey: ['styles'] });
      // Returned so the mutation stays pending until the matrix has refetched.
      return qc.invalidateQueries({ queryKey: ['admin', 'coverage'] });
    },
  });
}
