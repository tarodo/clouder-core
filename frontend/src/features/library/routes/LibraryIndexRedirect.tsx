import { Navigate } from 'react-router';

const DEFAULT_STYLE = 'drum-and-bass';

export function LibraryIndexRedirect() {
  return <Navigate to={`/library/${DEFAULT_STYLE}`} replace />;
}
