import { Tabs } from '@mantine/core';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';

interface Props {
  active: 'labels' | 'artists';
  styleId: string;
}

export function EntityTabs({ active, styleId }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <Tabs
      value={active}
      onChange={(v) => {
        if (v === 'labels') navigate(`/library/${styleId}`);
        else if (v === 'artists') navigate(`/library/${styleId}/artists`);
      }}
    >
      <Tabs.List>
        <Tabs.Tab value="labels">{t('library.entity_tabs.labels')}</Tabs.Tab>
        <Tabs.Tab value="artists">{t('library.entity_tabs.artists')}</Tabs.Tab>
      </Tabs.List>
    </Tabs>
  );
}
