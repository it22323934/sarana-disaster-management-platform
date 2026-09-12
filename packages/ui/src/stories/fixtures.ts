/**
 * Story fixtures.
 *
 * Real Sinhala and Tamil strings, not transliterations and not lorem. The whole point of
 * the three-script stories is to find the places where a Tamil label is 40% longer than
 * its English equivalent and breaks a layout, and placeholder text cannot do that.
 *
 * Place names are real districts and DS divisions. GN division codes follow the seeded
 * shape (`LK-DD-DD-DDD`); the boundaries behind them in `data/seed` are generated
 * rectangles around real district centroids, so these are plausible identifiers rather
 * than survey references. Nothing here is presented as a survey boundary.
 */

import type { Locale, LocalisedText } from '@sarana/ts-shared/i18n';

/** The three locales, in the order the stories iterate them. */
export const STORY_LOCALES: readonly Locale[] = ['en', 'si', 'ta'];

/**
 * A fixed instant, so every story renders identically on every run.
 *
 * 28 Nov 2025, 04:30 Colombo - the morning of the DMC press conference that went out in
 * Sinhala and English only.
 */
export const STORY_NOW = new Date('2025-11-27T23:00:00Z');

/** Cyclone Ditwah's landfall in the replay scenario. */
export const STORY_LANDFALL = '2025-11-28T00:00:00Z';

export const DIVISION_NAMES: readonly LocalisedText[] = [
  { si: 'පල්ලේකැලේ', ta: 'பள்ளேகலை', en: 'Pallekele' },
  { si: 'කඩවත', ta: 'கடவத்தை', en: 'Kadawatha' },
  { si: 'මහනුවර නගරය', ta: 'கண்டி நகரம்', en: 'Kandy Town' },
  { si: 'ගඟ ඉහළ කෝරළේ', ta: 'கங்க இஹல கோரளை', en: 'Ganga Ihala Korale' },
  { si: 'නාවලපිටිය', ta: 'நாவலப்பிட்டி', en: 'Nawalapitiya' },
];

export const DS_NAMES: readonly LocalisedText[] = [
  { si: 'ගඟ ඉහළ කෝරළේ', ta: 'கங்க இஹல கோரளை', en: 'Ganga Ihala Korale' },
  { si: 'මහනුවර', ta: 'கண்டி', en: 'Kandy' },
];

export interface StoryDivision {
  readonly code: string;
  readonly name: LocalisedText;
  readonly dsName: LocalisedText;
}

export const STORY_DIVISIONS: readonly StoryDivision[] = DIVISION_NAMES.map((name, index) => ({
  code: `LK-11-03-${String(index + 1).padStart(3, '0')}`,
  name,
  dsName: DS_NAMES[index % DS_NAMES.length] ?? DS_NAMES[0]!,
}));

/**
 * The longest realistic label for each locale, per common UI slot.
 *
 * These are what the overflow check measures. Tamil compound words in particular run
 * long: "ப்ரதேச செயலகப் பிரிவு" is 21 characters against "DS Division" at 11.
 */
export const LONGEST_LABELS: Record<string, LocalisedText> = {
  buttonPrimary: {
    si: 'අනතුරු ඇඟවීම යවන්න',
    ta: 'எச்சரிக்கையை அனுப்பவும்',
    en: 'Dispatch alert',
  },
  gateTitle: {
    si: 'අනුමැතිය බලාපොරොත්තුවෙන් සිටින යැවීම් 2ක්',
    ta: 'ஒப்புதலுக்காக காத்திருக்கும் 2 அனுப்புதல்கள்',
    en: '2 dispatches awaiting approval',
  },
  statLabel: {
    si: 'තහවුරු නොකළ ලබාදීම්',
    ta: 'உறுதிப்படுத்தப்படாத விநியோகங்கள்',
    en: 'Unconfirmed deliveries',
  },
  adminLevel: {
    si: 'ප්‍රාදේශීය ලේකම් කොට්ඨාසය',
    ta: 'பிரதேச செயலகப் பிரிவு',
    en: 'DS Division',
  },
  confidenceConsequence: {
    si: 'මානව සමාලෝචනය සඳහා යොමු කරන ලදී',
    ta: 'மனித மறுஆய்வுக்கு அனுப்பப்பட்டது',
    en: 'Routed to human review',
  },
  offlineQueued: {
    si: 'යැවීමට බලා සිටින වාර්තා 3ක්',
    ta: 'அனுப்ப காத்திருக்கும் 3 அறிக்கைகள்',
    en: '3 reports waiting to send',
  },
  emptyTitle: {
    si: 'මෙම කොට්ඨාසයේ සිදුවීම් නොමැත',
    ta: 'இந்தப் பிரிவில் சம்பவங்கள் இல்லை',
    en: 'No incidents in this division',
  },
  emptyDescription: {
    si: 'පෙරහන මගින් සිදුවීම් ඉවත් කර ඇත. පෙරහන ඉවත් කර නැවත උත්සාහ කරන්න.',
    ta: 'வடிகட்டி சம்பவங்களை நீக்குகிறது. வடிகட்டியை அகற்றி மீண்டும் முயற்சிக்கவும்.',
    en: 'The filter excludes them. Clear the filter and try again.',
  },
  translationIncomplete: {
    si: 'පරිවර්තනය අසම්පූර්ණයි',
    ta: 'மொழிபெயர்ப்பு முழுமையடையவில்லை',
    en: 'Translation incomplete',
  },
  translationComplete: {
    si: 'භාෂා තුනම සම්පූර්ණයි',
    ta: 'மூன்று மொழிகளும் முழுமையானவை',
    en: 'All three languages complete',
  },
  simulatedSource: {
    si: 'කාලගුණ විද්‍යා දෙපාර්තමේන්තුව',
    ta: 'வானிலை ஆய்வுத் துறை',
    en: 'Department of Meteorology',
  },
};

/** UI chrome strings the stories need. Mirrors the shape of the app catalogues. */
export const UI_STRINGS: Record<string, LocalisedText> = {
  language: { si: 'භාෂාව', ta: 'மொழி', en: 'Language' },
  dismiss: { si: 'ඉවත් කරන්න', ta: 'நிராகரி', en: 'Dismiss' },
  copy: { si: 'පිටපත් කරන්න', ta: 'நகலெடு', en: 'Copy' },
  copied: { si: 'පිටපත් කළා', ta: 'நகலெடுக்கப்பட்டது', en: 'Copied' },
  verify: { si: 'සත්‍යාපනය කරන්න', ta: 'சரிபார்', en: 'Verify' },
  previous: { si: 'පෙර', ta: 'முந்தையது', en: 'Previous' },
  next: { si: 'ඊළඟ', ta: 'அடுத்தது', en: 'Next' },
  review: { si: 'සමාලෝචනය කරන්න', ta: 'மறுஆய்வு செய்', en: 'Review' },
  online: { si: 'සබැඳිව', ta: 'இணைப்பில்', en: 'Online' },
  offline: { si: 'විසන්ධියි', ta: 'இணைப்பு இல்லை', en: 'Offline' },
  enableSound: { si: 'ශබ්දය සක්‍රීය කරන්න', ta: 'ஒலியை இயக்கு', en: 'Enable sound' },
  searchDivision: {
    si: 'ග්‍රාම නිලධාරී වසම සොයන්න',
    ta: 'கிராம சேவகர் பிரிவைத் தேடு',
    en: 'Search GN division',
  },
  incidentQueue: { si: 'සිදුවීම් පෝලිම', ta: 'சம்பவ வரிசை', en: 'Incident queue' },
  approvalHistory: { si: 'අනුමැති ඉතිහාසය', ta: 'ஒப்புதல் வரலாறு', en: 'Approval history' },
  timeline: { si: 'කාල රේඛාව', ta: 'கால வரிசை', en: 'Timeline' },
  youAreHere: { si: 'ඔබ මෙහි සිටී', ta: 'நீங்கள் இங்கே இருக்கிறீர்கள்', en: 'You are here' },
  recovery: { si: 'ප්‍රතිසාධනය', ta: 'மீட்பு', en: 'Recovery' },
  predictedImpact: { si: 'පුරෝකථිත බලපෑම', ta: 'கணிக்கப்பட்ட தாக்கம்', en: 'Predicted impact' },
};

export function pick(text: LocalisedText, locale: Locale): string {
  return text[locale];
}
