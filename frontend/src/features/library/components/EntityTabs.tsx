import { Tabs, Tooltip } from '@mantine/core';
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
      onChange={(v) => v === 'labels' && navigate(`/library/${styleId}`)}
    >
      <Tabs.List>
        <Tabs.Tab value="labels">{t('library.entity_tabs.labels')}</Tabs.Tab>
        <Tooltip label={t('library.entity_tabs.artists_coming_soon')}>
          <Tabs.Tab value="artists" data-disabled disabled>
            {t('library.entity_tabs.artists')}
          </Tabs.Tab>
        </Tooltip>
      </Tabs.List>
    </Tabs>
  );
}
