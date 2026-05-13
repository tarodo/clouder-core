import { useEffect, useState } from 'react';

export interface UndoEntry {
  id: string;
  label: string;
  undo: () => Promise<void> | void;
}

type Listener = () => void;

let current: UndoEntry | null = null;
const listeners = new Set<Listener>();

function emit(): void {
  for (const l of listeners) l();
}

export const undoStack = {
  push(entry: UndoEntry): void {
    current = entry;
    emit();
  },
  peek(): UndoEntry | null {
    return current;
  },
  async popAndRun(): Promise<void> {
    const entry = current;
    if (!entry) return;
    current = null;
    emit();
    await entry.undo();
  },
  clear(): void {
    current = null;
    emit();
  },
  subscribe(cb: Listener): () => void {
    listeners.add(cb);
    return () => {
      listeners.delete(cb);
    };
  },
};

export function useUndoStack(): { entry: UndoEntry | null } {
  const [entry, setEntry] = useState<UndoEntry | null>(undoStack.peek());
  useEffect(() => undoStack.subscribe(() => setEntry(undoStack.peek())), []);
  return { entry };
}
