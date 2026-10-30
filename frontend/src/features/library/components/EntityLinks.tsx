import { Anchor } from '@mantine/core';
import { Fragment } from 'react';
import { Link } from 'react-router';
import { AiRepBadge, type AiRep } from './AiRepBadge';

/** A name in running text that opens its artist or label page; keeps the text's size and color. */
export function EntityLink({ kind, id, name }: { kind: 'artist' | 'label'; id: string; name: string }) {
  return (
    <Anchor component={Link} to={`/${kind}s/${id}`} c="inherit" inherit>
      {name}
    </Anchor>
  );
}

/** Comma-joined artist names, each a link to its page and marked with its AI reputation. */
export function ArtistLinks({
  artists,
}: {
  artists: ReadonlyArray<{ id: string; name: string; ai?: AiRep | null }>;
}) {
  return artists.map((a, i) => (
    <Fragment key={i}>
      {i > 0 && ', '}
      <EntityLink kind="artist" id={a.id} name={a.name} />
      <AiRepBadge rep={a.ai} ml={4} />
    </Fragment>
  ));
}
