// <input> types that are widgets, not text entry — they should NOT suppress
// keyboard shortcuts (e.g. a Mantine Chip is a focusable <input type="checkbox">).
const NON_EDITABLE_INPUT_TYPES = new Set([
  'checkbox',
  'radio',
  'button',
  'submit',
  'reset',
  'file',
  'range',
  'color',
  'image',
]);

/**
 * True when a keyboard-event target is a genuine text-entry context, where
 * global shortcut handlers should stand down. Checkbox/radio/widget inputs
 * and non-input focusables (buttons, chips) are NOT editable.
 */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag === 'INPUT') {
    const type = (target as HTMLInputElement).type.toLowerCase();
    return !NON_EDITABLE_INPUT_TYPES.has(type);
  }
  if (target.isContentEditable) return true;
  return false;
}
