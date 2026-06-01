import { Text, Tooltip } from '@mantine/core';

export interface TrackKeyProps {
  /** Camelot code, e.g. "7B". */
  camelot?: string | null;
  /** Full key name for the tooltip, e.g. "F Major". */
  name?: string | null;
  size?: 'xs' | 'sm';
}

/** Renders the Camelot code with the full key name in a tooltip; em-dash when absent. */
export function TrackKey({ camelot, name, size = 'sm' }: TrackKeyProps) {
  if (!camelot) {
    return <Text size={size} c="dimmed" className="font-mono">—</Text>;
  }
  const text = <Text size={size} className="font-mono">{camelot}</Text>;
  return name ? <Tooltip label={name}>{text}</Tooltip> : text;
}
