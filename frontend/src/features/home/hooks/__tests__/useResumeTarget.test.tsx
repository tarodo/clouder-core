import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import {
  LAST_CURATE_LOCATION_KEY,
  LAST_CURATE_STYLE_KEY,
} from '../../../curate/lib/lastCurateLocation';
import { useResumeTarget } from '../useResumeTarget';
import type { TriageBlockSummary } from '../../../triage/hooks/useTriageBlocksByStyle';

function block(id: string, styleId: string, status: 'IN_PROGRESS' | 'FINALIZED', updatedAt: string): TriageBlockSummary {
  return {
    id, style_id: styleId, style_name: 'X', name: id, date_from: '2026-05-04',
    date_to: '2026-05-10', status, created_at: '2026-05-04T00:00:00Z',
    updated_at: updatedAt, finalized_at: null, track_count: 10,
  };
}

beforeEach(() => {
  localStorage.clear();
});

describe('useResumeTarget', () => {
  it('returns curate when localStorage points to an IN_PROGRESS block', () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'bk1', updatedAt: new Date().toISOString() } }),
    );
    const blocks = [block('b1', 's1', 'IN_PROGRESS', '2026-05-08T00:00:00Z')];
    const { result } = renderHook(() => useResumeTarget(blocks, { s1: blocks }));
    expect(result.current.kind).toBe('curate');
    if (result.current.kind === 'curate') {
      expect(result.current.session.bucketId).toBe('bk1');
      expect(result.current.block.id).toBe('b1');
    }
  });

  it('falls back to triage when block is FINALIZED, and clears localStorage', () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'bk1', updatedAt: new Date().toISOString() } }),
    );
    const finalized = block('b1', 's1', 'FINALIZED', '2026-05-08T00:00:00Z');
    const fallback = block('b2', 's1', 'IN_PROGRESS', '2026-05-09T00:00:00Z');
    const { result } = renderHook(() =>
      useResumeTarget([fallback], { s1: [finalized, fallback] }),
    );
    expect(result.current.kind).toBe('triage');
    expect(JSON.parse(localStorage.getItem(LAST_CURATE_LOCATION_KEY) ?? '{}')).toEqual({});
  });

  it('falls back when block is missing', () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b-gone', bucketId: 'bk1', updatedAt: new Date().toISOString() } }),
    );
    const fallback = block('b2', 's1', 'IN_PROGRESS', '2026-05-09T00:00:00Z');
    const { result } = renderHook(() =>
      useResumeTarget([fallback], { s1: [fallback] }),
    );
    expect(result.current.kind).toBe('triage');
  });

  it('falls back when localStorage entry is older than 7 days', () => {
    const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString();
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'bk1', updatedAt: eightDaysAgo } }),
    );
    const valid = block('b1', 's1', 'IN_PROGRESS', '2026-05-08T00:00:00Z');
    const { result } = renderHook(() =>
      useResumeTarget([valid], { s1: [valid] }),
    );
    expect(result.current.kind).toBe('triage');
    expect(JSON.parse(localStorage.getItem(LAST_CURATE_LOCATION_KEY) ?? '{}')).toEqual({});
  });

  it('returns triage when no localStorage but IN_PROGRESS blocks exist', () => {
    const b = block('b1', 's1', 'IN_PROGRESS', '2026-05-08T00:00:00Z');
    const { result } = renderHook(() => useResumeTarget([b], { s1: [b] }));
    expect(result.current.kind).toBe('triage');
  });

  it('returns empty when nothing is available', () => {
    const { result } = renderHook(() => useResumeTarget([], {}));
    expect(result.current.kind).toBe('empty');
  });
});
