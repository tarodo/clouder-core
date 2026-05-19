import { Code, Group, Button, Box } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';

export function RunJsonViewer({ data }: { data: unknown }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(data, null, 2);
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Box pos="relative">
      <Group justify="flex-end" mb="xs">
        <Button size="xs" variant="default" onClick={copy}>
          {copied ? t('admin_enrichment.run_detail.json_copied') : 'Copy JSON'}
        </Button>
      </Group>
      <Code block style={{ whiteSpace: 'pre-wrap' }}>{text}</Code>
    </Box>
  );
}
