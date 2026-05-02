import { Button, Group, Stack, Title } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useEffect } from 'react';
import { StyleSelector } from '../../../components/StyleSelector';
import { useStyles } from '../../../hooks/useStyles';
import { IconPlus } from '../../../components/icons';
import { TriageBlocksList } from '../components/TriageBlocksList';
import { CreateTriageBlockDialog } from '../components/CreateTriageBlockDialog';
import { writeLastVisitedTriageStyle } from '../lib/lastVisitedTriageStyle';

export function TriageListPage() {
  const { styleId } = useParams<{ styleId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { data: styles } = useStyles();
  const [opened, { open, close }] = useDisclosure(false);

  useEffect(() => {
    if (styleId) writeLastVisitedTriageStyle(styleId);
  }, [styleId]);

  if (!styleId) return null;

  const styleName = styles?.items.find((s) => s.id === styleId)?.name ?? '';

  return (
    <Stack gap="lg">
      <Group justify="space-between" wrap="nowrap">
        <Title order={2}>{t('triage.page_title')}</Title>
        <Group gap="md">
          <StyleSelector
            value={styleId}
            onChange={(next) => navigate(`/triage/${next}`)}
          />
          <Button leftSection={<IconPlus size={16} />} onClick={open}>
            {t('triage.create_cta')}
          </Button>
        </Group>
      </Group>

      <TriageBlocksList styleId={styleId} />

      <CreateTriageBlockDialog
        opened={opened}
        onClose={close}
        styleId={styleId}
        styleName={styleName}
      />
    </Stack>
  );
}
