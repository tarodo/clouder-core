import { CHANNELS, type ChannelMeta } from './channelMeta';

type ChannelSource = Partial<Record<ChannelMeta['field'], string | null | undefined>>;

export interface PickedChannel extends ChannelMeta {
  url: string;
}

export function pickTopChannels(source: ChannelSource, limit: number): PickedChannel[] {
  const result: PickedChannel[] = [];
  for (const ch of CHANNELS) {
    const url = source[ch.field];
    if (typeof url === 'string' && url.length > 0) {
      result.push({ ...ch, url });
      if (result.length >= limit) break;
    }
  }
  return result;
}
