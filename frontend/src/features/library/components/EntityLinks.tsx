import { Anchor } from '@mantine/core';
import { Fragment } from 'react';
import { Link } from 'react-router';

/** A name in running text that opens its artist or label page; keeps the text's size and color. */
export function EntityLink({ kind, id, name }: { kind: 'artist' | 'label'; id: string; name: string }) {
  return (
    <Anchor component={Link} to={`/${kind}s/${id}`} c="inherit" inherit>
      {name}
    </Anchor>
  );
}

/** Comma-joined artist names, each a link to its page. */
export function ArtistLinks({ artists }: { artists: ReadonlyArray<{ id: string; name: string }> }) {
  return artists.map((a, i) => (
    <Fragment key={i}>
      {i > 0 && ', '}
      <EntityLink kind="artist" id={a.id} name={a.name} />
    </Fragment>
  ));
}
