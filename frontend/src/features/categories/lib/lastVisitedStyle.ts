export const LAST_STYLE_KEY = 'clouder.lastStyleId';

export function readLastVisitedStyle(): string | null {
  try {
    return localStorage.getItem(LAST_STYLE_KEY);
  } catch {
    return null;
  }
}

export function writeLastVisitedStyle(styleId: string): void {
  try {
    localStorage.setItem(LAST_STYLE_KEY, styleId);
  } catch {
    /* private mode etc. — ignore */
  }
}
