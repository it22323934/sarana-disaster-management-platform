/**
 * The three public services, stubbed, on one port.
 *
 * **Why a server rather than browser-side interception.** web-ops routes its gateway calls
 * in the browser, because that is where its panels fetch. Nothing on this app fetches from
 * the browser: every figure is read server-side and rendered into the HTML, which is the
 * whole reason the pages work with JavaScript disabled. Intercepting in the page would
 * therefore intercept nothing, and the PII sweep and the no-JS suite — the two tests that
 * matter most here — would pass against an empty page.
 *
 * So the stub is a real HTTP server, and `next dev` is pointed at it through the same
 * environment variables the production deployment uses. What the suite exercises is the
 * real fetch path, the real `Result` handling, and the real render.
 *
 * **The fixtures are chosen to be hostile to the PII sweep, not friendly to it.** They
 * carry 64-character hex digests, twelve-digit cents amounts, UUIDs and mock payment
 * references — every shape that a careless PII regex flags. A sweep that only ever saw
 * small round numbers would prove nothing about the page it guards. The one thing they do
 * not carry is anything that actually is personal data, because that is what is being
 * asserted.
 *
 * One port for three services works because no two of them own the same path prefix, which
 * is the same property `apps/web-ops/src/lib/services.ts` relies on.
 */

import { createServer } from 'node:http';

const PORT = Number.parseInt(process.env.SARANA_STUB_PORT ?? '8099', 10);

/** A believable SHA-256, generated so consecutive entries differ. */
const hash = (seed) =>
  Array.from({ length: 64 }, (_, index) => '0123456789abcdef'[(seed * 31 + index * 7) % 16]).join('');

const DISTRICTS = [
  { code: 'LK-21', en: 'Kandy', si: 'මහනුවර', ta: 'கண்டி', province: 'LK-2' },
  { code: 'LK-11', en: 'Colombo', si: 'කොළඹ', ta: 'கொழும்பு', province: 'LK-1' },
  { code: 'LK-31', en: 'Galle', si: 'ගාල්ල', ta: 'காலி', province: 'LK-3' },
];

const funnel = {
  // Twelve digits in cents — Rs. 4.18bn. Deliberately the shape a naive NIC pattern
  // matches, so the sweep proves it distinguishes money from an identity number.
  assessed: { lkr_cents: 418234000000, count: 12847, of_previous: null },
  approved: { lkr_cents: 391022000000, count: 12010, of_previous: 0.935 },
  disbursed: { lkr_cents: 340211000000, count: 10440, of_previous: 0.87 },
  confirmed: { lkr_cents: 298145000000, count: 9146, of_previous: 0.876 },
  unconfirmed_count: 949,
  awaiting_reply_count: 345,
  reversed_count: 312,
  reversed_lkr_cents: 9420000000,
  households: 12847,
  gn_divisions: 214,
  grievance_count: 431,
  grievance_open_count: 88,
  last_disbursement_at: '2026-09-07T18:30:00+00:00',
  last_anchor_date: '2026-09-06',
  last_seq: 10440,
  as_of: '2026-09-08T02:00:00+00:00',
  confirmation_window_days: 7,
};

const districtMetrics = {
  districts: [
    {
      district_code: 'LK-21',
      assessed_count: 5120,
      assessed_households: 5001,
      assessed_divisions: 96,
      assessed_lkr_cents: 208234000000,
      approved_count: 4800,
      approved_lkr_cents: 191022000000,
      disbursed_count: 4200,
      disbursed_lkr_cents: 170211000000,
      confirmed_count: 3700,
      reversed_count: 120,
      confirmation_rate: 0.881,
      median_days_to_disbursement: 11.5,
      disbursed_per_household_lkr_cents: 34035392,
      grievance_count: 210,
      grievance_open_count: 40,
      grievance_rate_per_1000_disbursements: 50,
      last_released_at: '2026-09-07T18:30:00+00:00',
    },
    {
      district_code: 'LK-11',
      assessed_count: 4600,
      assessed_households: 4520,
      assessed_divisions: 74,
      assessed_lkr_cents: 150000000000,
      approved_count: 4100,
      approved_lkr_cents: 140000000000,
      disbursed_count: 3800,
      disbursed_lkr_cents: 120000000000,
      confirmed_count: 3500,
      reversed_count: 140,
      confirmation_rate: 0.921,
      median_days_to_disbursement: 6.2,
      disbursed_per_household_lkr_cents: 26548672,
      grievance_count: 150,
      grievance_open_count: 30,
      grievance_rate_per_1000_disbursements: 39.5,
      last_released_at: '2026-09-07T12:00:00+00:00',
    },
    {
      // Assessed and never paid. The most newsworthy row, and the one a naive query
      // would have dropped for having no disbursement.
      district_code: 'LK-31',
      assessed_count: 3127,
      assessed_households: 3326,
      assessed_divisions: 44,
      assessed_lkr_cents: 60000000000,
      approved_count: 3110,
      approved_lkr_cents: 60000000000,
      disbursed_count: 0,
      disbursed_lkr_cents: 0,
      confirmed_count: 0,
      reversed_count: 52,
      confirmation_rate: null,
      median_days_to_disbursement: null,
      disbursed_per_household_lkr_cents: 0,
      grievance_count: 71,
      grievance_open_count: 18,
      grievance_rate_per_1000_disbursements: null,
      last_released_at: null,
    },
  ],
  as_of: '2026-09-08T02:00:00+00:00',
  note: 'Administrative area codes, not names.',
};

const districtDetail = (code) => ({
  district_code: code,
  divisions: [
    {
      ds_division_code: `${code}-01`,
      assessed_count: 1200,
      assessed_households: 1180,
      assessed_divisions: 24,
      assessed_lkr_cents: 52000000000,
      approved_count: 1100,
      approved_lkr_cents: 48000000000,
      disbursed_count: 980,
      disbursed_lkr_cents: 42000000000,
      confirmed_count: 870,
      median_days_to_disbursement: 10.2,
    },
    {
      ds_division_code: `${code}-02`,
      assessed_count: 900,
      assessed_households: 890,
      assessed_divisions: 18,
      assessed_lkr_cents: 31000000000,
      approved_count: 850,
      approved_lkr_cents: 29000000000,
      disbursed_count: 0,
      disbursed_lkr_cents: 0,
      confirmed_count: 0,
      median_days_to_disbursement: null,
    },
  ],
  // Non-zero so the suppression banner renders and the sweep sees it.
  suppressed_divisions: 3,
  suppressed_disbursements: 7,
  suppressed_lkr_cents: 280000000,
  minimum_cell_size: 5,
  suppression_note: 'Withheld divisions are counted and their money is in the district total.',
  totals: {
    ds_division_code: code,
    assessed_count: 2100,
    assessed_households: 2070,
    assessed_divisions: 42,
    assessed_lkr_cents: 83000000000,
    approved_count: 1950,
    approved_lkr_cents: 77000000000,
    disbursed_count: 987,
    disbursed_lkr_cents: 42280000000,
    confirmed_count: 870,
    median_days_to_disbursement: null,
  },
  as_of: '2026-09-08T02:00:00+00:00',
});

const ledger = (fromSeq, limit) => {
  const entries = Array.from({ length: Math.min(limit, 25) }, (_, index) => {
    const seq = fromSeq + index + 1;
    return {
      seq,
      entitlement_id: `018f3c2a-0000-7e90-9c2d-${String(seq).padStart(12, '0')}`,
      amount_lkr_cents: 34000000 + seq * 1000,
      released_by: `018f3c2a-0009-7e90-9c2d-000000000009`,
      released_at: `2026-09-0${(seq % 7) + 1}T06:${String(seq % 60).padStart(2, '0')}:00+00:00`,
      payment_rail: 'BANK_TRANSFER',
      payment_ref: `MOCK-BANK_TRANSFER-${String(seq).padStart(12, '0')}`,
      prev_hash: seq === 1 ? '0'.repeat(64) : hash(seq - 1),
      entry_hash: hash(seq),
      reversed: seq % 17 === 0,
      anchor_date: `2026-09-0${(seq % 7) + 1}`,
    };
  });
  return {
    entries,
    next_seq: null,
    scheme: {
      entry_hash: 'SHA256( canonical_json(entry_without_hashes) || prev_hash )',
      canonical_json: 'RFC 8785 JSON Canonicalization Scheme',
      genesis_prev_hash: '64 zero characters',
      verifier: 'tools/sarana-verify in the SARANA repository',
    },
    note: 'Every entry, anonymised.',
  };
};

const anchors = {
  anchors: [1, 2, 3].map((day) => ({
    date: `2026-09-0${day}`,
    merkle_root: hash(100 + day),
    entry_count: 1200 + day,
    first_seq: day * 1200,
    last_seq: day * 1200 + 1199,
    prev_anchor_hash: day === 1 ? null : hash(100 + day - 1),
    // The first day has no store configured. The page must say so rather than show a
    // plausible URI, and the suite asserts the banner appears.
    s3_object_lock_uri: day === 1 ? null : `s3://sarana-anchors/2026-09-0${day}.json`,
    published_at: `2026-09-0${day}T18:30:00+00:00`,
  })),
  scheme: {
    merkle_leaf: 'SHA256( canonical_json(entry_without_hashes) )',
    merkle_pair: 'SHA256( left_hex || right_hex )',
    merkle_odd_node: 'the last node is duplicated and paired with itself',
  },
};

const schedules = [
  {
    id: '018f3c2a-1000-7e90-9c2d-000000000001',
    version: '2026.1',
    published_at: '2026-01-15T00:00:00+00:00',
    source_ref: 'Gazette Extraordinary 2266/14',
    effective_from: '2026-02-01',
    effective_to: null,
    lines: [
      {
        id: '018f3c2a-2000-7e90-9c2d-000000000001',
        category: 'HOUSE_FULL',
        subcategory: '',
        description: {
          en: 'House fully damaged',
          si: 'නිවස සම්පූර්ණයෙන් හානි වී ඇත',
          ta: 'வீடு முழுமையாகச் சேதமடைந்தது',
        },
        unit: 'dwelling',
        rate_lkr_cents: 250000000,
        cap_lkr_cents: 400000000,
        formula: { kind: 'flat_rate', expression: 'min(rate * quantity, cap)' },
      },
      {
        id: '018f3c2a-2000-7e90-9c2d-000000000002',
        category: 'LIVELIHOOD',
        subcategory: 'FISHING_GEAR',
        description: {
          en: 'Fishing gear replacement',
          si: 'ධීවර උපකරණ ප්‍රතිස්ථාපනය',
          ta: 'மீன்பிடி உபகரணங்கள் மாற்றீடு',
        },
        unit: 'set',
        rate_lkr_cents: 7500000,
        cap_lkr_cents: null,
        formula: { kind: 'per_unit', expression: 'rate * quantity' },
      },
    ],
  },
];

const grievances = {
  districts: [
    {
      district_code: 'LK-21',
      total: 210,
      open_count: 40,
      closed_count: 170,
      breached_count: 12,
      median_resolution_seconds: 604800,
    },
    {
      district_code: 'UNASSIGNED',
      total: 18,
      open_count: 18,
      closed_count: 0,
      breached_count: 4,
      median_resolution_seconds: null,
    },
  ],
  note: 'A low complaint count is not evidence of a low error rate.',
};

const confirmationRate = {
  released: 10440,
  confirmed: 9146,
  unconfirmed: 949,
  awaiting_reply: 345,
  confirmation_rate: 0.876,
  window_days: 7,
  note: 'unconfirmed is not failed.',
};

const alerts = {
  alerts: [
    {
      id: '018f3c2a-0008-7e90-9c2d-000000000008',
      cap_identifier: 'urn:sarana:alert:2026-09-07:0001',
      headline: {
        en: 'Landslide warning — Kandy district',
        si: 'නායයෑම් අනතුරු ඇඟවීම — මහනුවර දිස්ත්‍රික්කය',
        ta: 'நிலச்சரிவு எச்சரிக்கை — கண்டி மாவட்டம்',
      },
      description: {
        en: 'Heavy rain has saturated slopes across the district.',
        si: 'අධික වර්ෂාව නිසා දිස්ත්‍රික්කය පුරා බෑවුම් සංතෘප්ත වී ඇත.',
        ta: 'கனமழையால் மாவட்டம் முழுவதும் சரிவுகள் நிறைவுற்றுள்ளன.',
      },
      instruction: {
        en: 'Move to the nearest safe location now.',
        si: 'දැන්ම ආසන්නතම ආරක්ෂිත ස්ථානයට යන්න.',
        ta: 'உடனே அருகிலுள்ள பாதுகாப்பான இடத்திற்குச் செல்லுங்கள்.',
      },
      severity: 'SEVERE',
      urgency: 'IMMEDIATE',
      certainty: 'LIKELY',
      status: 'DISPATCHED',
      effective_at: '2026-09-07T18:00:00+00:00',
      // Far enough out that the alert is active whenever the suite runs.
      expires_at: '2099-01-01T00:00:00+00:00',
      active: true,
      gn_division_count: 96,
      targeted: 12043,
      reached: 4210,
      cap_xml_url: '/api/v1/alerts/018f3c2a-0008-7e90-9c2d-000000000008/cap.xml',
    },
    {
      id: '018f3c2a-0010-7e90-9c2d-000000000010',
      cap_identifier: 'urn:sarana:alert:2026-09-05:0002',
      headline: {
        en: 'Flood warning — withdrawn',
        si: 'ගංවතුර අනතුරු ඇඟවීම — ඉවත් කරගත්',
        ta: 'வெள்ள எச்சரிக்கை — திரும்பப் பெறப்பட்டது',
      },
      description: { en: 'Withdrawn after the river level fell.', si: 'ගං මට්ටම පහත වැටීමෙන් පසු ඉවත් කරගන්නා ලදී.', ta: 'ஆற்று மட்டம் குறைந்த பின் திரும்பப் பெறப்பட்டது.' },
      instruction: { en: 'No action required.', si: 'ක්‍රියාමාර්ගයක් අවශ්‍ය නොවේ.', ta: 'நடவடிக்கை தேவையில்லை.' },
      severity: 'MODERATE',
      urgency: 'PAST',
      certainty: 'OBSERVED',
      status: 'CANCELLED',
      effective_at: '2026-09-05T06:00:00+00:00',
      expires_at: '2026-09-06T06:00:00+00:00',
      active: false,
      gn_division_count: 12,
      targeted: 3100,
      reached: 2980,
      cap_xml_url: '/api/v1/alerts/018f3c2a-0010-7e90-9c2d-000000000010/cap.xml',
    },
  ],
  active_count: 1,
  as_of: '2026-09-08T02:00:00+00:00',
  note: 'Alerts that were actually dispatched.',
};

const areaDistricts = {
  districts: DISTRICTS.map((district) => ({
    code: district.code,
    name: { en: district.en, si: district.si, ta: district.ta },
    province_code: district.province,
    province_name: { en: 'Central', si: 'මධ්‍යම', ta: 'மத்திய' },
    gn_division_count: 96,
    population: 1375000,
    household_count: 340000,
    centroid_lon: 80.6337,
    centroid_lat: 7.2906,
  })),
};

const areaDsDivisions = (code) => ({
  ds_divisions: [1, 2].map((index) => ({
    code: `${code}-0${index}`,
    name: {
      en: `Division ${index}`,
      si: `කොට්ඨාසය ${index}`,
      ta: `பிரிவு ${index}`,
    },
    district_code: code,
    gn_division_count: 24,
    population: 180000,
    household_count: 45000,
  })),
});

const geojson = {
  type: 'FeatureCollection',
  is_generated: true,
  note: 'Generated boundaries, not survey boundaries.',
  features: DISTRICTS.map((district, index) => ({
    type: 'Feature',
    id: district.code,
    properties: { district_code: district.code },
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [80.4 + index * 0.4, 7.1],
          [80.8 + index * 0.4, 7.1],
          [80.8 + index * 0.4, 7.5],
          [80.4 + index * 0.4, 7.5],
          [80.4 + index * 0.4, 7.1],
        ],
      ],
    },
  })),
};

function route(pathname, search) {
  const params = new URLSearchParams(search);

  if (pathname === '/api/v1/public/funnel') return funnel;
  if (pathname === '/api/v1/public/districts') return districtMetrics;
  if (pathname.startsWith('/api/v1/public/districts/')) {
    return districtDetail(pathname.split('/').pop());
  }
  if (pathname === '/api/v1/public/confirmation-rate') return confirmationRate;
  if (pathname === '/api/v1/public/grievances') return grievances;
  if (pathname === '/api/v1/cost-schedules') return schedules;
  if (pathname === '/api/v1/ledger/anchors') return anchors;
  if (pathname === '/api/v1/ledger/public') {
    return ledger(
      Number.parseInt(params.get('from_seq') ?? '0', 10) || 0,
      Number.parseInt(params.get('limit') ?? '200', 10) || 200,
    );
  }
  if (pathname === '/api/v1/public/alerts') return alerts;
  if (pathname === '/api/v1/public/areas/districts') return areaDistricts;
  if (pathname === '/api/v1/public/areas/ds-divisions') {
    return areaDsDivisions(params.get('district_code') ?? 'LK-21');
  }
  if (pathname === '/api/v1/public/areas/districts.geojson') return geojson;
  return null;
}

createServer((request, response) => {
  const url = new URL(request.url ?? '/', `http://127.0.0.1:${PORT}`);
  const body = route(url.pathname, url.search);

  if (body === null) {
    // 404 rather than an empty 200. A stub that answered every path would hide a typo in
    // a fetcher's URL and the suite would test a page rendering the wrong fixture.
    response.writeHead(404, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify({ error: 'not_found', path: url.pathname }));
    return;
  }

  response.writeHead(200, { 'Content-Type': 'application/json' });
  response.end(JSON.stringify(body));
}).listen(PORT, '127.0.0.1', () => {
  console.log(`stub services on http://127.0.0.1:${PORT}`);
});
