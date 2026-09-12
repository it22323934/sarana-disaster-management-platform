/**
 * The Open Graph card for one district.
 *
 * The brief asks for these "so a shared link previews the actual number", and that is the
 * whole design: a link pasted into a newsroom Slack should show what was disbursed in
 * Kandy without anybody clicking through, because the click is where most readers are lost.
 *
 * Three constraints shape what is on it.
 *
 * **It says the data is simulated, in the image.** A preview card is the most screenshotted
 * and least contextualised artefact this site produces — it travels into chat threads and
 * slide decks with no page around it. The `MockDataBadge` in the header does not travel
 * with it, so the statement is rendered into the picture.
 *
 * **It is Latin script only, and it is the same card in all three locales.** `ImageResponse`
 * rasterises text with fonts it is given, and no Noto Sinhala or Noto Tamil face is
 * vendored in this repository (a known gap from file 19). Rendering Sinhala with a fallback
 * would produce boxes, and a card full of tofu is worse than a card in English — so the
 * card carries the district *code*, the money, and a label short enough to be unambiguous,
 * rather than a name it cannot draw.
 *
 * **It never shows a number it could not read.** If the metrics fetch fails the card says
 * so rather than rendering `Rs. 0`, for the same reason every page does.
 */

import { ImageResponse } from 'next/og';

import { formatLKR } from '../../../../src/lib/format';
import { getDistrictMetrics } from '../../../../src/lib/public-api';

export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

/** `LK-21`. A junk code renders the "unknown district" card rather than throwing. */
const DISTRICT_CODE = /^LK-\d{2}$/;

export default async function DistrictOgImage({
  params,
}: {
  readonly params: { readonly code: string };
}) {
  const { code } = params;
  const metrics = DISTRICT_CODE.test(code) ? await getDistrictMetrics() : null;
  const row = metrics?.ok
    ? metrics.data.districts.find((candidate) => candidate.district_code === code)
    : undefined;

  const disbursed = row ? formatLKR(row.disbursed_lkr_cents, { whole: true }) : null;
  const households = row ? row.assessed_households.toLocaleString('en-LK') : null;

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          // The light theme's surfaces, hard-coded: `ImageResponse` has no CSS custom
          // properties and no stylesheet, so the tokens cannot be referenced here.
          background: '#FBFCFD',
          color: '#101720',
          padding: 64,
          fontFamily: 'sans-serif',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ fontSize: 28, color: '#4A5A70' }}>SARANA Aid Transparency</div>
          <div style={{ fontSize: 64, fontWeight: 700 }}>{code}</div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 30, color: '#4A5A70' }}>Disbursed</div>
          <div style={{ fontSize: 84, fontWeight: 700 }}>
            {disbursed ?? 'Figure unavailable'}
          </div>
          {households ? (
            <div style={{ fontSize: 30, color: '#4A5A70' }}>
              {households} households assessed
            </div>
          ) : null}
        </div>

        <div
          style={{
            display: 'flex',
            alignSelf: 'flex-start',
            fontSize: 26,
            fontWeight: 600,
            color: '#9E5604',
            background: '#F7EDE0',
            border: '2px solid #BC7728',
            borderRadius: 8,
            padding: '10px 18px',
          }}
        >
          Simulated data — prototype, no government system connected
        </div>
      </div>
    ),
    size,
  );
}
