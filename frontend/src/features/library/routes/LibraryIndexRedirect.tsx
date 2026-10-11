import { Navigate } from 'react-router';
import { isDemo } from '../../../demo/mode';

// The demo's sample catalog has no drum and bass.
const DEFAULT_STYLE = isDemo() ? 'tech-house' : 'drum-and-bass';

export function LibraryIndexRedirect() {
  return <Navigate to={`/library/${DEFAULT_STYLE}`} replace />;
}
