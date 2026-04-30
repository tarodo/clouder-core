import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

const root = document.getElementById('root');
if (!root) throw new Error('#root missing');

createRoot(root).render(
  <StrictMode>
    <main style={{ fontFamily: 'system-ui', padding: 24 }}>
      <h1>CLOUDER frontend boot OK</h1>
    </main>
  </StrictMode>,
);
