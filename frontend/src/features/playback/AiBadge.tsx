import { Badge } from '@mantine/core';

/** The audio analyzer flagged this track as AI-generated (ai_lofcz). A signal, not a verdict. */
export function AiBadge() {
  return (
    <Badge color="orange" variant="light" size="xs" style={{ flexShrink: 0 }}>
      AI
    </Badge>
  );
}
