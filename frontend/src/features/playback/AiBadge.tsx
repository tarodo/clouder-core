import { Badge } from '@mantine/core';

type AiLevel = 'high' | 'medium' | 'low';

// high = ai_lofcz and ai_deezer both flagged, medium = lofcz only, low = Deezer only.
const COLOR: Record<AiLevel, string> = { high: 'red', medium: 'orange', low: 'yellow' };

/** The AI level as one "AI" badge whose color carries the level. A signal, not proof. */
export function AiBadge({ verdict }: { verdict?: AiLevel | null }) {
  if (!verdict) return null;
  return (
    <Badge
      color={COLOR[verdict]}
      variant="light"
      size="xs"
      style={{ flexShrink: 0 }}
      data-level={verdict}
    >
      AI
    </Badge>
  );
}
