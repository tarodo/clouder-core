import type { ComponentType } from 'react';
import {
  IconWorld,
  IconBrandBandcamp,
  IconBrandSoundcloud,
  IconBrandInstagram,
  IconBrandTwitter,
  IconLink,
} from '@tabler/icons-react';

export type ChannelKind =
  | 'website'
  | 'bandcamp'
  | 'soundcloud'
  | 'beatport'
  | 'residentadvisor'
  | 'discogs'
  | 'instagram'
  | 'twitter';

export interface ChannelMeta {
  kind: ChannelKind;
  field:
    | 'website'
    | 'bandcamp_url'
    | 'soundcloud_url'
    | 'beatport_url'
    | 'residentadvisor_url'
    | 'discogs_url'
    | 'instagram_url'
    | 'twitter_url';
  Icon: ComponentType<{ size?: number }>;
  i18nKey: string;
}

export const CHANNELS: ReadonlyArray<ChannelMeta> = [
  { kind: 'website',          field: 'website',          Icon: IconWorld,            i18nKey: 'library.channels.website' },
  { kind: 'soundcloud',       field: 'soundcloud_url',   Icon: IconBrandSoundcloud,  i18nKey: 'library.channels.soundcloud' },
  { kind: 'bandcamp',         field: 'bandcamp_url',     Icon: IconBrandBandcamp,    i18nKey: 'library.channels.bandcamp' },
  { kind: 'beatport',         field: 'beatport_url',     Icon: IconLink,             i18nKey: 'library.channels.beatport' },
  { kind: 'residentadvisor',  field: 'residentadvisor_url', Icon: IconLink,         i18nKey: 'library.channels.residentadvisor' },
  { kind: 'discogs',          field: 'discogs_url',      Icon: IconLink,             i18nKey: 'library.channels.discogs' },
  { kind: 'instagram',        field: 'instagram_url',    Icon: IconBrandInstagram,   i18nKey: 'library.channels.instagram' },
  { kind: 'twitter',          field: 'twitter_url',      Icon: IconBrandTwitter,     i18nKey: 'library.channels.twitter' },
];
