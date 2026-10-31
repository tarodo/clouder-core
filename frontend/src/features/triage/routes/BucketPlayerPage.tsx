import { Stack, ActionIcon, Group, Text } from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';
import { useNavigate, useOutletContext, useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { BucketPlayerPanel } from '../components/BucketPlayerPanel';
import type { BucketTrack } from '../hooks/useBucketTracks';
import { useTriageBlock } from '../hooks/useTriageBlock';
import { bucketLabel } from '../lib/bucketLabels';

export interface BucketDetailOutletContext {
  items: BucketTrack[];
}

// Nested under BucketDetailPage; the parent owns the queue binding + search
// state. This page renders the panel + a back link for the mobile layout.
export function BucketPlayerPage() {
  const { styleId, id, bucketId } = useParams<{
    styleId: string;
    id: string;
    bucketId: string;
  }>();
  if (!styleId || !id || !bucketId) return <Navigate to="/triage" replace />;
  return <BucketPlayerPageInner styleId={styleId} blockId={id} bucketId={bucketId} />;
}

function BucketPlayerPageInner({
  styleId,
  blockId,
  bucketId,
}: {
  styleId: string;
  blockId: string;
  bucketId: string;
}) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const ctx = useOutletContext<BucketDetailOutletContext | undefined>();
  const items = ctx?.items ?? [];
  const { data: block } = useTriageBlock(blockId);
  const bucket = block?.buckets.find((b) => b.id === bucketId);
  return (
    <Stack gap="md" p="md">
      <Group>
        <ActionIcon
          variant="subtle"
          onClick={() => navigate(`/triage/${styleId}/${blockId}/buckets/${bucketId}`)}
          aria-label={t('triage.bucket_player.back_aria')}
        >
          <IconArrowLeft />
        </ActionIcon>
        {/* which style's triage this is: categories repeat across styles */}
        {block && bucket && (
          <Text size="sm" c="dimmed">
            {block.style_name} · {bucketLabel(bucket, t)}
          </Text>
        )}
      </Group>
      <BucketPlayerPanel blockId={blockId} bucketId={bucketId} items={items} />
    </Stack>
  );
}
