export const LAST_TRIAGE_STYLE_KEY = 'clouder.lastTriageStyleId';

export function readLastVisitedTriageStyle(): string | null {
  try {
    return localStorage.getItem(LAST_TRIAGE_STYLE_KEY);
  } catch {
    return null;
  }
}

export function writeLastVisitedTriageStyle(styleId: string): void {
  try {
    localStorage.setItem(LAST_TRIAGE_STYLE_KEY, styleId);
  } catch {
    /* private mode etc. — ignore */
  }
}
