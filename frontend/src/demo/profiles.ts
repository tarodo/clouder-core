/**
 * What the demo's Library knows about its invented labels and artists. Labels are written by
 * hand; artist profiles are assembled from a few phrase lists so 24 of them read differently.
 * No links: a made-up name must not point at someone's real account.
 */

export interface LabelProfile {
  country: string;
  founded_year: number;
  tagline: string;
  summary: string;
  secondary_styles: string[];
}

export interface ArtistProfile {
  country: string;
  active_since: number;
  artist_type: 'solo' | 'duo';
  tagline: string;
  summary: string;
  bio: string;
}

export const LABEL_PROFILES: Record<string, LabelProfile> = {
  'Lowtide Records': {
    country: 'PT',
    founded_year: 2016,
    tagline: 'Sun-bleached house from the Lisbon coast',
    summary:
      'A small Lisbon label for warm, percussive records that suit the first hours of a night. Every release is a three-track EP with a dub on the B-side.',
    secondary_styles: ['Deep House'],
  },
  Northbound: {
    country: 'NO',
    founded_year: 2014,
    tagline: 'Cold, hypnotic grooves from the far north',
    summary:
      'Run out of a converted boathouse near Tromsø, the label favours long, patient arrangements and basslines that roll rather than drop.',
    secondary_styles: ['Minimal / Deep Tech'],
  },
  'Palette Audio': {
    country: 'NL',
    founded_year: 2011,
    tagline: 'Club tools in bright colours',
    summary:
      'A Rotterdam imprint built around DJ-friendly tools: clean intros, clear breakdowns and one vocal hook per record.',
    secondary_styles: ['Techno (Peak Time)'],
  },
  'Coral Tapes': {
    country: 'ZA',
    founded_year: 2019,
    tagline: 'Percussion first, everything else after',
    summary:
      'Born in Durban, the label records live percussion before anything else is written. Releases often credit the session players by name.',
    secondary_styles: ['Organic House'],
  },
  Hinterland: {
    country: 'DE',
    founded_year: 2009,
    tagline: 'Long melodic journeys, released slowly',
    summary:
      'A Leipzig label that puts out four or five records a year, each built around a slow melodic arc meant for the middle of a long set.',
    secondary_styles: ['Progressive House'],
  },
  'Dense Grid': {
    country: 'GB',
    founded_year: 2018,
    tagline: 'Tight, rolling drums for peak-time rooms',
    summary:
      'A Bristol label for hard-swinging grooves: shuffled hats, short vocal stabs and drums that keep a room moving.',
    secondary_styles: ['Techno (Peak Time)'],
  },
};

const COUNTRIES: [string, string][] = [
  ['DE', 'Berlin'],
  ['NL', 'Amsterdam'],
  ['GB', 'London'],
  ['PT', 'Lisbon'],
  ['ZA', 'Johannesburg'],
  ['FR', 'Lyon'],
  ['IT', 'Milan'],
  ['ES', 'Valencia'],
  ['SE', 'Gothenburg'],
  ['BR', 'São Paulo'],
  ['CA', 'Montréal'],
  ['AU', 'Melbourne'],
];

const TAGLINES: Record<string, string[]> = {
  'Melodic House & Techno': [
    'Patient builds with analogue pads',
    'Melancholy melodies for the last hour',
    'Arpeggios that take their time',
    'Wide pads and slow-burning breakdowns',
    'Cinematic techno for the small hours',
    'Hypnotic sequences, warm analogue tones',
  ],
  'Afro House': [
    'Percussion-led house with live instruments',
    'Shakers, talking drums and a deep kick',
    'Warm afro grooves with choir-like vocals',
    'Kalimba melodies over deep, rolling drums',
    'Spiritual house built on live percussion',
    'Polyrhythms for the golden hour',
  ],
};

const SOUND = [
  'builds tracks around a single bassline and lets the drums do the talking',
  'records most of the percussion by hand before opening the laptop',
  'writes long intros and outros so other DJs can mix in and out with ease',
  'mixes vintage drum machines with field recordings from home',
  'keeps arrangements sparse and leaves room for the crowd',
];

const STORY = [
  'Started on a borrowed controller at school parties, then spent years warming up for touring DJs.',
  'Came to dance music from jazz, and still plays keys on most records.',
  'Ran a small monthly night for five years before the first release came out.',
  'Learned production by remaking old club records note for note.',
  'Splits the week between a studio job in film sound and late sessions on club music.',
];

/** A profile for one invented artist; `pick` is the seed's random source. */
export function buildArtistProfile(
  name: string,
  styles: string[],
  pick: <T>(xs: readonly T[]) => T,
  index: number,
): ArtistProfile {
  const [country, city] = pick(COUNTRIES);
  const style = styles[0] ?? 'Melodic House & Techno';
  const duo = index % 7 === 3;
  const active_since = 2010 + ((index * 5) % 13);
  return {
    country,
    active_since,
    artist_type: duo ? 'duo' : 'solo',
    tagline: pick(TAGLINES[style] ?? TAGLINES['Melodic House & Techno'] ?? ['Club music']),
    summary: `${name} is a ${duo ? 'duo' : 'producer'} from ${city} making ${style.toLowerCase()} since ${active_since}; ${duo ? 'the duo' : 'the project'} ${pick(SOUND)}.`,
    bio: `${pick(STORY)} ${name} plays out most weekends and releases a few EPs a year.`,
  };
}
