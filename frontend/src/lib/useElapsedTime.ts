import { useEffect, useState } from 'react';

export function useElapsedTime(running: boolean): number {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!running) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const id = setInterval(() => {
      setElapsed(Date.now() - start);
    }, 250);
    return () => clearInterval(id);
  }, [running]);

  return elapsed;
}
