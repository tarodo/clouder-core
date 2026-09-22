/**
 * True when a keydown carries a browser/OS chord modifier (Ctrl, Cmd, Alt).
 * Those chords belong to the browser — Cmd/Ctrl/Alt + digit switches tabs,
 * Cmd+L focuses the address bar, Cmd+F opens find — so app shortcuts must
 * stand down instead of swallowing them with preventDefault().
 *
 * Shift is deliberately NOT included: it is part of our own chords
 * (Shift+J/K seek, `?` opens the help overlay).
 */
export function hasSystemModifier(event: KeyboardEvent): boolean {
  return event.ctrlKey || event.metaKey || event.altKey;
}
