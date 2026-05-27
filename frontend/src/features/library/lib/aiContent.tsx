import { Badge, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export const AI_COLOR: Record<string, string> = {
  none_detected: 'green',
  unknown: 'gray',
  suspected: 'yellow',
  confirmed: 'red',
};

export function formatAiContent(value: string): string {
  return `AI ${value.toUpperCase()}`;
}

interface AiContentBadgeProps {
  /** ai_content enum value; empty string renders nothing. */
  content: string;
  reasoning?: string;
  /** 'colored' (detail header) or 'outline' (compact player tile). */
  variant?: 'colored' | 'outline';
}

/** Tooltip-wrapped AI badge. Returns null when `content` is empty. */
export function AiContentBadge({ content, reasoning = '', variant = 'colored' }: AiContentBadgeProps) {
  const { t } = useTranslation();
  if (!content) return null;

  const badge =
    variant === 'outline' ? (
      <Badge
        variant="outline"
        style={{ cursor: 'help', backgroundColor: 'white', color: 'black', borderColor: 'black' }}
      >
        {formatAiContent(content)}
      </Badge>
    ) : (
      <Badge color={AI_COLOR[content] ?? 'gray'} variant="light" style={{ cursor: 'help' }}>
        {formatAiContent(content)}
      </Badge>
    );

  return (
    <Tooltip
      label={reasoning || t('library.detail.ai_reasoning_missing')}
      multiline
      w={300}
      withinPortal
      events={{ hover: true, focus: true, touch: true }}
      styles={{
        tooltip: {
          backgroundColor: 'white',
          color: 'black',
          padding: '12px 16px',
          lineHeight: 1.5,
          border: '1px solid var(--mantine-color-gray-3)',
          boxShadow: 'var(--mantine-shadow-md)',
        },
      }}
    >
      {badge}
    </Tooltip>
  );
}
