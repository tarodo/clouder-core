import { describe, it, expect } from 'vitest';
import { isEditableTarget } from '../isEditableTarget';

describe('isEditableTarget', () => {
  it('text-entry inputs are editable', () => {
    const text = document.createElement('input'); // type defaults to "text"
    expect(isEditableTarget(text)).toBe(true);
    const email = document.createElement('input');
    email.type = 'email';
    expect(isEditableTarget(email)).toBe(true);
    expect(isEditableTarget(document.createElement('textarea'))).toBe(true);
    expect(isEditableTarget(document.createElement('select'))).toBe(true);
  });

  it('checkbox/radio/widget inputs are NOT editable', () => {
    for (const type of ['checkbox', 'radio', 'button', 'submit', 'reset', 'file', 'range', 'color', 'image']) {
      const el = document.createElement('input');
      el.type = type;
      expect(isEditableTarget(el)).toBe(false);
    }
  });

  it('non-element / plain elements are not editable', () => {
    expect(isEditableTarget(null)).toBe(false);
    expect(isEditableTarget(document.createElement('div'))).toBe(false);
    expect(isEditableTarget(document.createElement('button'))).toBe(false);
  });
});
