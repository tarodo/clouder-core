import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { CommentsPanel } from './CommentsPanel';
import * as hook from '../hooks/useTrackComments';
import type { TrackCommentsResponse } from '../lib/playlistTypes';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

function renderPanel() {
  return render(
    <MantineProvider>
      <CommentsPanel trackId="t1" />
    </MantineProvider>,
  );
}

function mockHook(data: Partial<TrackCommentsResponse> | undefined, opts: Partial<{ isLoading: boolean }> = {}) {
  vi.spyOn(hook, 'useTrackComments').mockReturnValue({
    data: data as TrackCommentsResponse | undefined,
    isLoading: opts.isLoading ?? false,
  } as ReturnType<typeof hook.useTrackComments>);
}

describe('CommentsPanel', () => {
  it('renders up to 5 collected comments', () => {
    mockHook({
      status: 'collected',
      comment_count: 2,
      video_url: 'https://youtube.com/watch?v=v',
      comments: [
        { author_name: 'Alice', author_avatar_url: null, text: 'hello', like_count: 3, published_at: null },
        { author_name: 'Bob', author_avatar_url: null, text: 'world', like_count: 0, published_at: null },
      ],
    });
    renderPanel();
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('shows pending state', () => {
    mockHook({ status: 'pending', comment_count: 0, video_url: null, comments: [] });
    renderPanel();
    expect(screen.getByText('comments.pending')).toBeInTheDocument();
  });

  it('shows empty state for empty/disabled', () => {
    mockHook({ status: 'empty', comment_count: 0, video_url: null, comments: [] });
    renderPanel();
    expect(screen.getByText('comments.empty')).toBeInTheDocument();
  });

  it('renders nothing on failed', () => {
    mockHook({ status: 'failed', comment_count: 0, video_url: null, comments: [] });
    renderPanel();
    // MantineProvider injects <style> tags so we cannot assert toBeEmptyDOMElement;
    // instead verify no visible content is rendered.
    expect(document.querySelector('[role], h1, h2, h3, p, a, button, span:not([data-mantine-styles])')).toBeNull();
  });
});
