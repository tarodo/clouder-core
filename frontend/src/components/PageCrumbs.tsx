import { createContext, useContext, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

/**
 * The app header's slot for the page's breadcrumbs / back link. Undefined outside the app shell;
 * null inside it until the header has mounted the slot.
 */
export const PageCrumbsSlot = createContext<HTMLElement | null | undefined>(undefined);

/** The page's breadcrumbs / back link, shown in the app header instead of a row of the page. */
export function PageCrumbs({ children }: { children: ReactNode }) {
  const slot = useContext(PageCrumbsSlot);
  if (slot === undefined) return children;
  return slot ? createPortal(children, slot) : null;
}
