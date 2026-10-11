/** True in the GitHub Pages demo build (`vite build --mode demo`). */
export const isDemo = (): boolean => import.meta.env.MODE === 'demo';
