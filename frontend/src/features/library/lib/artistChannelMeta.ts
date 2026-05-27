import type { ComponentType } from 'react';
import {
  IconWorld,
  IconBrandBandcamp,
  IconBrandSoundcloud,
  IconBrandInstagram,
  IconBrandTwitter,
  IconBrandSpotify,
  IconLink,
} from '@tabler/icons-react';

export type ArtistChannelKind =
  | 'spotify'
  | 'soundcloud'
  | 'bandcamp'
  | 'beatport'
  | 'residentadvisor'
  | 'discogs'
  | 'instagram'
  | 'twitter'
  | 'website';

export interface ArtistChannelMeta {
  kind: ArtistChannelKind;
  field:
    | 'spotify_url'
    | 'soundcloud_url'
    | 'bandcamp_url'
    | 'beatport_url'
    | 'residentadvisor_url'
    | 'discogs_url'
    | 'instagram_url'
    | 'twitter_url'
    | 'website';
  Icon: ComponentType<{ size?: number }>;
  i18nKey: string;
}

export const ARTIST_CHANNELS: ReadonlyArray<ArtistChannelMeta> = [
  { kind: 'spotify',        field: 'spotify_url',         Icon: IconBrandSpotify,    i18nKey: 'library.channels.spotify' },
  { kind: 'soundcloud',     field: 'soundcloud_url',      Icon: IconBrandSoundcloud, i18nKey: 'library.channels.soundcloud' },
  { kind: 'bandcamp',       field: 'bandcamp_url',        Icon: IconBrandBandcamp,   i18nKey: 'library.channels.bandcamp' },
  { kind: 'beatport',       field: 'beatport_url',        Icon: IconLink,            i18nKey: 'library.channels.beatport' },
  { kind: 'residentadvisor', field: 'residentadvisor_url', Icon: IconLink,           i18nKey: 'library.channels.residentadvisor' },
  { kind: 'discogs',        field: 'discogs_url',         Icon: IconLink,            i18nKey: 'library.channels.discogs' },
  { kind: 'instagram',      field: 'instagram_url',       Icon: IconBrandInstagram,  i18nKey: 'library.channels.instagram' },
  { kind: 'twitter',        field: 'twitter_url',         Icon: IconBrandTwitter,    i18nKey: 'library.channels.twitter' },
  { kind: 'website',        field: 'website',             Icon: IconWorld,           i18nKey: 'library.channels.website' },
];
