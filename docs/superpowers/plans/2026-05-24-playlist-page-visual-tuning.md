# Playlist Page Visual Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eight visual tweaks on the playlist detail page (`/playlists/:id`) plus making the track-list tags read-only.

**Architecture:** Frontend-only. Grouped by file to avoid touching `PlaylistDetailPage` in two tasks. No backend/type changes.

**Tech Stack:** React 19 + Mantine 9 + dnd-kit + TypeScript; Vitest/jsdom. Run from `frontend/`. (Backend venv lives at the MAIN repo root — not used here.)

---

## Task 1: Cover picker — click-to-replace, limits inside placeholder

**Files:**
- Modify: `frontend/src/features/playlists/components/CoverPicker.tsx`
- Test: `frontend/src/features/playlists/components/__tests__/CoverPicker.test.tsx` (create if absent)
- i18n: `frontend/src/i18n/en.json` — add `playlists.cover.upload_hint`.

- [ ] **Step 1: Write/adjust the failing test**

Assert: no "Replace cover" button (`screen.queryByRole('button', { name: /replace/i })` is null); a file input exists (`container.querySelector('input[type="file"]')`); with `coverUrl=null` the limits help text renders. (Render in `MantineProvider` + `ModalsProvider` since remove uses `modals`.) Run → fails (Replace button still present).

- [ ] **Step 2: Rebuild `CoverPicker`**

Make the avatar the click target and move the limits text inside the empty placeholder. Keep `handleFile`/`handleRemove`/`resetRef`/hooks as-is. Replace the returned JSX:

```tsx
  return (
    <Stack gap="xs" align="center">
      <Box style={{ position: 'relative', width: 160 }}>
        <FileButton accept="image/jpeg,image/png" onChange={handleFile} resetRef={resetRef}>
          {(props) => (
            <UnstyledButton
              {...props}
              aria-label={t('playlists.cover.replace')}
              style={{ display: 'block', borderRadius: 'var(--mantine-radius-md)' }}
            >
              <Avatar
                src={coverUrl}
                alt={t('playlists.cover.placeholder_alt')}
                size={160}
                radius="md"
                color="gray"
                style={{ cursor: 'pointer' }}
              >
                <Stack gap={4} align="center" justify="center" px="xs">
                  <IconPhoto size={36} />
                  <Text size="xs" c="dimmed" ta="center">
                    {t('playlists.cover.help_text')} ({Math.floor(MAX_COVER_BYTES / 1024)} KB)
                  </Text>
                  <Text size="xs" c="dimmed" ta="center">
                    {t('playlists.cover.upload_hint')}
                  </Text>
                </Stack>
              </Avatar>
            </UnstyledButton>
          )}
        </FileButton>
        {coverUrl ? (
          <ActionIcon
            variant="filled"
            color="dark"
            size="sm"
            onClick={handleRemove}
            loading={clear.isPending}
            aria-label={t('playlists.cover.remove')}
            style={{ position: 'absolute', top: 6, right: 6 }}
          >
            <IconTrash size={14} />
          </ActionIcon>
        ) : null}
        <LoadingOverlay visible={upload.isPending} overlayProps={{ radius: 'md' }} />
      </Box>
    </Stack>
  );
```

Update imports: add `Box`, `UnstyledButton`, `LoadingOverlay`; drop `Button`, `IconUpload`, `Group` if now unused (let typecheck/lint tell you). `Avatar` children only render when `coverUrl` is null (Mantine shows the image otherwise), so the limits hint shows only on the empty cover.

- [ ] **Step 3: Add the i18n key**

In `en.json`, under `playlists.cover`, add `"upload_hint": "Click to upload"`.

- [ ] **Step 4: Run + commit**

Run: `cd frontend && pnpm typecheck && pnpm test -- CoverPicker`
Then:
```bash
git add frontend/src/features/playlists/components/CoverPicker.tsx frontend/src/features/playlists/components/__tests__/CoverPicker.test.tsx frontend/src/i18n/en.json
git commit -m "fix(playlists): click cover to replace, limits inside empty placeholder"
```

---

## Task 2: Publish button + description width

**Files:**
- Modify: `frontend/src/features/playlists/components/PublishButton.tsx` (C)
- Modify: `frontend/src/features/playlists/components/PlaylistMetaPanel.tsx` (B)

- [ ] **Step 1: Soften the Publish button**

In `PublishButton.tsx`, change the `<Button color="green" ...>` (line ~87) to a soft green (light fill + border, matching tag pills):

```tsx
        <Button
          leftSection={<IconBrandSpotify size={16} />}
          color="green"
          variant="light"
          style={{ border: '1px solid var(--mantine-color-green-3)' }}
          loading={publishMut.isPending}
          onClick={handleClick}
        >
```

- [ ] **Step 2: Cap the description width**

In `PlaylistMetaPanel.tsx`, the description has two modes. Cap both at 520px:
- View-mode `<Box ... style={{ position:'relative', ... }}>` (line ~150): add `maxWidth: 520` to its style object.
- Edit-mode wrapper `<Group gap="xs" wrap="nowrap" align="flex-start">` holding the `<Textarea>` (line ~128): add `style={{ maxWidth: 520 }}` to that `Group`.

- [ ] **Step 3: Run + commit**

Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm test -- PublishButton PlaylistMetaPanel`
(These may have no/few tests — typecheck + any existing tests passing is enough.)
```bash
git add frontend/src/features/playlists/components/PublishButton.tsx frontend/src/features/playlists/components/PlaylistMetaPanel.tsx
git commit -m "fix(playlists): soft-green publish button, capped description width"
```

---

## Task 3: Track tile + list + page (meta line, read-only tags, Remove text, controls, buttons)

**Files:**
- Modify: `frontend/src/features/playlists/components/PlaylistTrackRow.tsx` (G, H, I)
- Modify: `frontend/src/features/playlists/components/PlaylistTracksList.tsx` (H)
- Modify: `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx` (H, D, E, F)
- Test: `frontend/src/features/playlists/components/__tests__/PlaylistTrackRow.test.tsx`

- [ ] **Step 1: Update the row test (failing)**

In `PlaylistTrackRow.test.tsx`:
- Replace the existing "removes a tag by clicking the colored pill" test with one asserting tags are **read-only**: `expect(screen.queryByRole('button', { name: /remove dark/i })).toBeNull()` (the tag pill is no longer an interactive remove button), while `screen.getByText('Dark')` still renders.
- Add: the meta line renders a single ` | `-joined string — assert `screen.getByText(/Ostgut Ton \| 140 BPM \| 6:30 \| 2024-03-15/)` (matching the `richTrack` fixture).
- Keep the Remove-track assertion (`getByRole('button', { name: /remove/i })` → `onRemove` fires) — it now matches the subtle text button.

Run: `cd frontend && pnpm test -- PlaylistTrackRow` → fails.

- [ ] **Step 2: `PlaylistTrackRow.tsx` — meta line (G), read-only tags (H), Remove text (I)**

Drop `onRemoveTag` from `PlaylistTrackRowProps` (and thus `ViewProps`) — remove it from the interface and the destructure.

Replace the line-2 `<Group>` (the label/bpm/length/release Texts + tags map) with:

```tsx
        <Group gap="xs" wrap="wrap" align="center">
          <Text size="xs" c="dimmed">
            {[
              track.label?.name ?? '—',
              track.bpm != null ? `${track.bpm} BPM` : null,
              formatLength(track.length_ms),
              formatReleaseDate(track.spotify_release_date),
            ]
              .filter(Boolean)
              .join(' | ')}
          </Text>
          {/* Read-only in the list — tags are edited in the player. */}
          {track.tags.map((tag) => (
            <TagPill key={tag.id} name={tag.name} color={tag.color} />
          ))}
        </Group>
```

Replace the Remove `<Button>` (line ~168) with a pale-red text button:

```tsx
      {/* Remove track — pale-red text, low emphasis */}
      <Button variant="subtle" color="red" size="xs" onClick={() => onRemove(track)}>
        {t('playlists.detail.remove_track_cta')}
      </Button>
```

(`formatLength`/`formatReleaseDate` return `''` for null, dropped by `filter(Boolean)`; label falls back to `—`.)

- [ ] **Step 3: `PlaylistTracksList.tsx` — drop the tag prop (H)**

Remove `onRemoveTag` from `PlaylistTracksListProps`, the destructure, and the `<PlaylistTrackRow onRemoveTag={...}>` thread. The `DragOverlay` clone never passed it. Done.

- [ ] **Step 4: `PlaylistDetailPage.tsx` — controls above list (E), Add Tracks soft (D), search width (F), drop tag wiring (H)**

- **D + F (controls):** Change the Add Tracks `<Button leftSection={<IconPlus/>}>` to `variant="light"`; change the search `TextInput` `style={{ flex: 1, minWidth: 200 }}` → `style={{ width: 280 }}`.
- **E (placement):** Move `{controls}` from between `<PlaylistMetaPanel>` and `<Flex>` into the top of `tilesList`, so it sits directly above the list in both layouts. Make `tilesList`:

```tsx
  const tilesList = (
    <Stack gap="md">
      {controls}
      {tracks.length === 0 ? (
        <EmptyState
          title={t('playlists.detail.empty_tracks_title')}
          body={t('playlists.detail.empty_tracks_body')}
        />
      ) : (
        <PlaylistTracksList
          tracks={filtered}
          onReorder={search.trim() === '' ? handleReorder : () => {}}
          onRemove={handleRemoveTrack}
          reorderDisabled={search.trim() !== ''}
          onPlayTrack={onPlay}
          currentTrackId={playback.track.current?.id ?? null}
        />
      )}
    </Stack>
  );
```

Remove the standalone `{controls}` line (and its comment) between the meta panel and the `{isDesktop ? <Flex> ... }`.

- **H (drop tag wiring):** Remove `import { usePlaylistRemoveTrackTag }`, the `const removeTagMut = usePlaylistRemoveTrackTag(id);` line, the `const onRemoveTag = useCallback(...)` block, and the `onRemoveTag={onRemoveTag}` prop (already removed from the list above). Remove the now-unused `PlaylistTrackTag` type import if present.

- [ ] **Step 5: Run + commit**

Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm test -- PlaylistTrackRow PlaylistTracksList PlaylistDetailPage`
Expected: green.
```bash
git add frontend/src/features/playlists/components/PlaylistTrackRow.tsx frontend/src/features/playlists/components/PlaylistTracksList.tsx frontend/src/features/playlists/routes/PlaylistDetailPage.tsx frontend/src/features/playlists/components/__tests__/PlaylistTrackRow.test.tsx
git commit -m "fix(playlists): pipe meta line, read-only list tags, text remove, controls above list"
```

---

## Task 4: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Gate**

Run, paste summaries:
- `cd frontend && pnpm typecheck && pnpm lint && pnpm test`
- `cd frontend && pnpm test:browser`

Expected: all PASS (pre-existing lint WARNINGS acceptable). The `PlaylistTrackRow.browser.test.tsx` smoke (play/number/Remove visible) still passes — the Remove text button still matches `name: /remove/i`.

- [ ] **Step 2: Commit (only if a fix was needed)**

```bash
git add -A
git commit -m "chore(frontend): fixups for playlist visual tuning"
```

---

## Done criteria

- Cover: no Replace button / help-text line; clicking the cover opens the picker; empty cover shows the limits hint inside; filled cover has a corner remove icon.
- Description box capped (~520px); Publish soft-green (light + border); Add Tracks `variant="light"`; controls (Add/Import/Search) directly above the list; search fixed width (~280px).
- Track line 2 = `Label | 87 BPM | 3:44 | 2026-05-04`; list tags read-only; Remove is pale-red text.
- `pnpm typecheck && pnpm lint && pnpm test` + `pnpm test:browser` all green.

## Post-merge verification (user, visual)

Cover click/replace/remove + empty-state text; description not full-width; softer Publish/Add Tracks; controls above the list; search not stretched; track meta with ` | ` separators + "BPM"; tags non-clickable in the list; Remove as pale-red text.
