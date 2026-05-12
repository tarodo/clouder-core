import { useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  List,
  Modal,
  Stack,
  Textarea,
  Text,
  Title,
} from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { parseSpotifyRef, InvalidSpotifyRefError } from '../lib/spotifyRefParse';
import { useImportSpotifyTracks } from '../hooks/useImportSpotifyTracks';
import { ApiError } from '../../../api/error';
import type { ImportSpotifyResult } from '../lib/playlistTypes';

const MAX_REFS = 50;

export interface ImportSpotifyModalProps {
  opened: boolean;
  onClose: () => void;
  playlistId: string;
}

interface RefValidation {
  raw: string;
  valid: boolean;
}

function validateRefs(text: string): RefValidation[] {
  return text
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .map((raw) => {
      try {
        parseSpotifyRef(raw);
        return { raw, valid: true };
      } catch (e) {
        if (e instanceof InvalidSpotifyRefError) return { raw, valid: false };
        return { raw, valid: false };
      }
    });
}

export function ImportSpotifyModal({ opened, onClose, playlistId }: ImportSpotifyModalProps) {
  const { t } = useTranslation();
  const importMut = useImportSpotifyTracks();
  const [text, setText] = useState('');
  const [result, setResult] = useState<ImportSpotifyResult | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const lines = useMemo(() => validateRefs(text), [text]);
  const validCount = lines.filter((l) => l.valid).length;
  const tooMany = lines.length > MAX_REFS;
  const canSubmit = validCount > 0 && !tooMany;

  async function handleSubmit() {
    setServerError(null);
    const refs = lines.filter((l) => l.valid).map((l) => l.raw);
    try {
      const r = await importMut.mutateAsync({ playlistId, spotifyRefs: refs });
      setResult(r);
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) {
        setServerError(t('playlists.errors.spotify_not_authorized'));
      } else if (err instanceof ApiError && err.status === 502) {
        setServerError(t('playlists.errors.spotify_upstream_error'));
      } else {
        setServerError(t('playlists.toast.generic_error'));
      }
    }
  }

  function handleClose() {
    setText('');
    setResult(null);
    setServerError(null);
    onClose();
  }

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      size="lg"
      title={t('playlists.import.title')}
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        {serverError ? (
          <Alert color="red" icon={<IconAlertTriangle size={16} />}>
            {serverError}
          </Alert>
        ) : null}
        <Textarea
          label={t('playlists.import.textarea_label')}
          placeholder={t('playlists.import.textarea_placeholder')}
          autosize
          minRows={5}
          maxRows={12}
          value={text}
          onChange={(e) => setText(e.currentTarget.value)}
        />
        <Group justify="space-between">
          <Text c="dimmed" size="sm">
            {lines.length === 0
              ? ''
              : tooMany
                ? t('playlists.import.max_exceeded')
                : `${validCount}/${lines.length} valid`}
          </Text>
          <Button
            onClick={() => void handleSubmit()}
            loading={importMut.isPending}
            disabled={!canSubmit}
          >
            {t('playlists.import.submit')}
          </Button>
        </Group>

        {result ? (
          <Stack gap="xs">
            <Title order={5}>{t('playlists.import.added', { count: result.added.length })}</Title>
            <List size="sm">
              {result.added.map((a) => (
                <List.Item key={a.track_id}>{a.title}</List.Item>
              ))}
            </List>
            {result.skipped.length > 0 ? (
              <>
                <Title order={5}>{t('playlists.import.skipped', { count: result.skipped.length })}</Title>
                <List size="sm">
                  {result.skipped.map((s, i) => (
                    <List.Item key={`${s.ref}-${i}`}>
                      <Text size="sm" inherit>
                        {s.ref} — {t(`playlists.import.reason_${s.reason}`)}
                      </Text>
                    </List.Item>
                  ))}
                </List>
              </>
            ) : null}
          </Stack>
        ) : null}
      </Stack>
    </Modal>
  );
}
