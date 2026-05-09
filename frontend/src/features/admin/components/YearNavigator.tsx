import { ActionIcon, Group, Select, Text } from '@mantine/core';
import { weeksInYear } from '../lib/saturdayWeek';

interface Props {
  year: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
}

export function YearNavigator({ year, onChange, min = 2024, max = 2030 }: Props) {
  const years: string[] = [];
  for (let y = min; y <= max; y += 1) years.push(String(y));
  return (
    <Group gap="xs" align="center">
      <ActionIcon
        variant="default"
        aria-label="Previous year"
        disabled={year <= min}
        onClick={() => onChange(year - 1)}
      >
        ‹
      </ActionIcon>
      <Select
        data={years}
        value={String(year)}
        onChange={(v) => v && onChange(Number(v))}
        w={110}
        aria-label="Year"
      />
      <ActionIcon
        variant="default"
        aria-label="Next year"
        disabled={year >= max}
        onClick={() => onChange(year + 1)}
      >
        ›
      </ActionIcon>
      <Text size="sm" c="dimmed">
        {weeksInYear(year)} weeks
      </Text>
    </Group>
  );
}
