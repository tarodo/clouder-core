import { Badge } from '@mantine/core';

/**
 * The AI pair verdict (ai_lofcz + ai_deezer): both flagged → "AI", one → a paler
 * "AI?". A signal, not proof; nothing without a verdict.
 */
export function AiBadge({ verdict }: { verdict?: 'ai' | 'review' | null }) {
  if (!verdict) return null;
  const review = verdict === 'review';
  return (
    <Badge color={review ? 'gray' : 'orange'} variant="light" size="xs" style={{ flexShrink: 0 }}>
      {review ? 'AI?' : 'AI'}
    </Badge>
  );
}
