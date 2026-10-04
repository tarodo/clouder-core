import { Button, Checkbox, Popover, ScrollArea, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { CoveragePayload } from '../hooks/useCoverage';
import { useSetStyleHidden } from '../hooks/useSetStyleHidden';

interface Props {
  styles: CoveragePayload['styles'];
}

export function StyleVisibilityPopover({ styles }: Props) {
  const { t } = useTranslation();
  const setHidden = useSetStyleHidden();
  const hiddenCount = styles.filter((s) => s.is_hidden).length;

  return (
    <Popover position="bottom-end" shadow="md">
      <Popover.Target>
        <Button variant="default" size="xs">
          {hiddenCount > 0
            ? t('admin.coverage.styles_hidden', { count: hiddenCount })
            : t('admin.coverage.styles')}
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs" maw={260}>
          <Text size="xs" c="dimmed">
            {t('admin.coverage.styles_hint')}
          </Text>
          <ScrollArea.Autosize mah={320}>
            <Stack gap={6}>
              {styles.map((s) => (
                <Checkbox
                  key={s.clouder_style_id}
                  label={s.style_name}
                  checked={!s.is_hidden}
                  disabled={setHidden.isPending}
                  onChange={(e) =>
                    setHidden.mutate({
                      styleId: s.clouder_style_id,
                      isHidden: !e.currentTarget.checked,
                    })
                  }
                />
              ))}
            </Stack>
          </ScrollArea.Autosize>
          {setHidden.isError && (
            <Text size="xs" c="red">
              {t('admin.coverage.styles_toggle_failed')}
            </Text>
          )}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
