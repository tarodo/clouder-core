// frontend/src/features/curate/components/HotkeyOverlay.tsx
import { Group, Kbd, Modal, Stack, Table, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';

export interface HotkeyOverlayProps {
  opened: boolean;
  onClose: () => void;
  hasOverflow: boolean;
}

interface KeyRow {
  keys: string[];
  labelKey: string;
}

const ASSIGN: KeyRow[] = [
  { keys: ['1', '…', '9'], labelKey: 'curate.hotkeys.key_digits_label' },
  { keys: ['Q', 'W', 'E'], labelKey: 'curate.hotkeys.key_qwe_label' },
  { keys: ['0'], labelKey: 'curate.hotkeys.key_zero_label' },
];
const NAVIGATE: KeyRow[] = [
  { keys: ['J'], labelKey: 'curate.hotkeys.key_j_label' },
  { keys: ['K'], labelKey: 'curate.hotkeys.key_k_label' },
];
const ACTION: KeyRow[] = [
  { keys: ['Space'], labelKey: 'curate.hotkeys.key_space_label' },
  { keys: ['U'], labelKey: 'curate.hotkeys.key_u_label' },
];
const SYSTEM: KeyRow[] = [
  { keys: ['?'], labelKey: 'curate.hotkeys.key_help_label' },
  { keys: ['Esc'], labelKey: 'curate.hotkeys.key_esc_label' },
  { keys: ['Enter'], labelKey: 'curate.hotkeys.key_enter_label' },
];

function KeyTable({ rows, t }: { rows: KeyRow[]; t: ReturnType<typeof useTranslation>['t'] }) {
  return (
    <Table withRowBorders={false}>
      <Table.Tbody>
        {rows.map((row) => (
          <Table.Tr key={row.labelKey}>
            <Table.Td style={{ width: 120 }}>
              <Group gap={4}>
                {row.keys.map((k) => (
                  <Kbd key={k}>{k}</Kbd>
                ))}
              </Group>
            </Table.Td>
            <Table.Td>{t(row.labelKey)}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function HotkeyOverlay({ opened, onClose, hasOverflow }: HotkeyOverlayProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('curate.hotkeys.title')}
      size="md"
      centered
      closeButtonProps={{ 'aria-label': 'Close' }}
    >
      <Stack gap="md">
        {isMobile ? (
          <>
            <Text>{t('curate.hotkeys.mobile_note')}</Text>
            <KeyTable rows={ACTION} t={t} />
            <KeyTable rows={SYSTEM} t={t} />
          </>
        ) : (
          <>
            <Text fw={600} size="sm">
              {t('curate.hotkeys.section_assign')}
            </Text>
            <KeyTable rows={ASSIGN} t={t} />
            <Text fw={600} size="sm">
              {t('curate.hotkeys.section_navigate')}
            </Text>
            <KeyTable rows={NAVIGATE} t={t} />
            <Text fw={600} size="sm">
              {t('curate.hotkeys.section_action')}
            </Text>
            <KeyTable rows={ACTION} t={t} />
            <Text fw={600} size="sm">
              {t('curate.hotkeys.section_system')}
            </Text>
            <KeyTable rows={SYSTEM} t={t} />
          </>
        )}
        <Text size="xs" c="var(--color-fg-muted)">
          {t('curate.hotkeys.footer_audio_note')}
        </Text>
        {hasOverflow && (
          <Text size="xs" c="var(--color-fg-muted)">
            {t('curate.hotkeys.footer_overflow_note')}
          </Text>
        )}
      </Stack>
    </Modal>
  );
}
