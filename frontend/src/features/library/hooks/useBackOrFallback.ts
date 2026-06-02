import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router';

/**
 * Returns a handler that goes back one history entry when in-app history
 * exists, otherwise navigates to `fallback`. react-router sets
 * `location.key === 'default'` only for the first/only entry (deep-link or
 * fresh tab) where there is nothing to go back to.
 */
export function useBackOrFallback(fallback: string): () => void {
  const navigate = useNavigate();
  const location = useLocation();
  return useCallback(() => {
    if (location.key !== 'default') {
      navigate(-1);
    } else {
      navigate(fallback);
    }
  }, [navigate, location.key, fallback]);
}
