/**
 * Every route, in all three scripts, checked for the layout failure that actually happens.
 *
 * Build file 20 asks for "every route renders correctly in si, ta, and en with no overflow
 * (visual regression)". This is that gate, and the form it takes is a decision.
 *
 * **It measures overflow rather than comparing pixels.** A screenshot baseline suite would
 * be the literal reading, and it would be worse here: baselines are captured on one
 * operating system with one set of installed fonts, and this repository is developed on
 * Windows against a CI that is not. Every baseline would differ for reasons that have
 * nothing to do with the console, which produces the suite the e2e configuration already
 * warns about — one that fails for unrelated reasons and that nobody runs. Worse, a
 * screenshot diff flags *any* change, so the signal for the one failure that matters
 * arrives buried in noise from every intentional edit.
 *
 * The failure that matters is specific and this measures it directly: **a Sinhala or Tamil
 * string breaking a layout that fits in English.** The same flood warning is one segment in
 * English and two in Sinhala from the alphabet alone, and the width ratios run to 1.5x — so
 * a slot sized to its English content is a slot that overflows in the two languages most of
 * the country reads. That is not a hypothetical: `packages/ui` gates 15 slots against a
 * width *model* for exactly this reason, and this is the same question asked of whole
 * screens in a real browser, where the model cannot help.
 *
 * Two assertions per route per locale:
 *
 *   1. The document does not scroll horizontally. A console that does is one where a
 *      dispatcher loses a column off the right edge on the hardware an operations room has.
 *   2. No element clips its own content. An element whose `overflow-x` is `hidden` and
 *      whose content is wider than its box is text somebody cannot read — which in this
 *      product is a division name, a reference code or a warning.
 *
 * Containers that scroll on purpose are excluded, and so is anything inside one: the queue
 * virtualiser, the data tables and the map all scroll by design, and the brief asks for
 * them to. `sr-only` is excluded because clipping is how it works.
 */

import type { Page } from '@playwright/test';

import {
  ALERT_ID,
  ENTITLEMENT_ID,
  INCIDENT_ID,
  PLAN_ID,
  alertBody,
  dryRunBody,
  entitlementBody,
  expect,
  forecastBody,
  incidentBody,
  planBody,
  reasoningBody,
  responderBody,
  scriptGateway,
  signInAs,
  test,
  type GatewayScript,
} from './fixtures';

/** The three scripts. Ordered with English last so a failure names the interesting one. */
const LOCALES = ['si', 'ta', 'en'] as const;

/**
 * Every route the console serves, with its dynamic segments filled in.
 *
 * Written out rather than discovered from the file system. A generated list would silently
 * shrink when a route moved, and this suite would keep passing while covering less — which
 * is the failure mode of a coverage gate that measures itself.
 */
const ROUTES: readonly string[] = [
  '/login',
  '/totp',
  '/ops',
  '/ops/incidents',
  `/ops/incidents/${INCIDENT_ID}`,
  '/ops/dispatch',
  `/ops/dispatch/${PLAN_ID}`,
  '/ops/alerts',
  '/ops/alerts/new',
  `/ops/alerts/${ALERT_ID}`,
  `/ops/alerts/${ALERT_ID}/delivery`,
  '/ops/forecast',
  '/ops/review',
  '/field/assessments',
  '/field/assessments/new',
  '/approvals',
  `/approvals/${ENTITLEMENT_ID}`,
  '/disbursements',
  `/disbursements/${ENTITLEMENT_ID}`,
  '/grievances',
  '/audit',
  '/audit/anomalies',
  '/audit/chain',
  '/admin',
];

/**
 * One gateway script that answers for every screen.
 *
 * Populated rather than empty. An empty response renders an empty state, and an empty
 * state is the layout least likely to overflow — a suite that measured those would pass
 * while every populated screen was broken. The strings are deliberately the long ones: a
 * real division name, a real organisation, a real detector name.
 */
function everything(): GatewayScript[] {
  return [
    { match: `dispatch-plans/${PLAN_ID}`, body: planBody({ reasoning: reasoningBody() }) },
    { match: 'dispatch-plans', body: [planBody()] },
    { match: `incidents/${INCIDENT_ID}`, body: incidentBody() },
    {
      match: 'incidents/queue',
      body: {
        assisted: false,
        banner: 'Assisted triage unavailable - manual ordering',
        ordering: 'triage-rules-1',
        entries: [
          {
            ...incidentBody(),
            score: 0.71,
            model_version: 'triage-rules-1',
            factors: { severity: 0.4, people_at_risk: 0.31 },
          },
        ],
      },
    },
    { match: 'incidents', body: [incidentBody()] },
    { match: 'responders', body: [responderBody()] },
    { match: 'impact-forecasts', body: [forecastBody()] },
    { match: 'anticipatory-triggers', body: [] },
    {
      match: 'hazard-events',
      body: [
        {
          id: '018f3c2a-0011-7e90-9c2d-000000000011',
          type: 'CYCLONE',
          name: { si: 'ඩිත්වා සුළිකුණාටුව', ta: 'திட்வா சூறாவளி', en: 'Cyclone Ditwah' },
          source: 'DMC',
          source_ref: 'DMC-2025-11-28',
          declared_at: new Date(Date.now() - 72 * 3_600_000).toISOString(),
          landfall_at: new Date(Date.now() - 6 * 3_600_000).toISOString(),
          status: 'RESPONSE',
        },
      ],
    },
    { match: `entitlements/${ENTITLEMENT_ID}`, body: entitlementBody() },
    {
      match: 'entitlements',
      body: [
        {
          id: ENTITLEMENT_ID,
          assessment_id: '018f3c2a-0004-7e90-9c2d-000000000004',
          assessment_ref: 'CLM-251128-A1B2C3',
          household_id: '018f3c2a-0005-7e90-9c2d-000000000005',
          gn_division_code: 'LK-11-03-045',
          category: 'HOUSE_PARTIAL',
          cost_schedule_version: '2025.11',
          calculated_lkr_cents: 12_500_000,
          calculated_at: new Date(Date.now() - 3 * 3_600_000).toISOString(),
          status: 'APPROVED',
          approved_levels: ['DS'],
          released: false,
        },
      ],
    },
    { match: `alerts/${ALERT_ID}/dispatch`, body: dryRunBody() },
    {
      match: `alerts/${ALERT_ID}/delivery/gaps`,
      body: [
        {
          gn_division_code: 'LK-11-03-045',
          targeted: 480,
          confirmed: 121,
          confirmed_fraction: 0.252,
          summary: '121 of 480 targeted households confirmed delivery in this division.',
        },
      ],
    },
    {
      match: `alerts/${ALERT_ID}/delivery`,
      body: {
        targeted: 1203,
        confirmed: 865,
        unconfirmed: 300,
        failed: 20,
        no_channel: 18,
        by_channel: { SMS: { CONFIRMED: 800, FAILED: 20 } },
        by_language: { si: 700, ta: 300, en: 203 },
        summary: '865 of 1,203 targeted households confirmed delivery.',
      },
    },
    { match: `alerts/${ALERT_ID}`, body: alertBody() },
    { match: 'alerts', body: [] },
    {
      match: 'templates',
      body: [
        {
          id: '018f3c2a-000b-7e90-9c2d-00000000000b',
          code: 'FLOOD_WARNING',
          hazard_type: 'FLOOD',
          severity: 'SEVERE',
          urgency: 'EXPECTED',
          certainty: 'LIKELY',
          body: {
            si: '{gn_division_name} ප්‍රදේශයේ ගංවතුර අනතුරු ඇඟවීම. වහාම උස් බිමකට යන්න.',
            ta: '{gn_division_name} பகுதியில் வெள்ள எச்சரிக்கை. உடனடியாக உயரமான இடத்திற்குச் செல்லுங்கள்.',
            en: 'Flood warning for {gn_division_name}. Move to higher ground now.',
          },
          reviewed_by_si: '018f3c2a-000c-7e90-9c2d-00000000000c',
          reviewed_by_ta: '018f3c2a-000d-7e90-9c2d-00000000000d',
          reviewed_at: '2025-11-20T00:00:00Z',
          version: 1,
          status: 'PUBLISHED',
        },
      ],
    },
    {
      match: 'admin/users',
      body: [
        {
          id: '018f3c2a-0013-7e90-9c2d-000000000013',
          email: 'district.approver.kandy@dmc.gov.lk',
          full_name: 'District Approver, Kandy',
          status: 'ACTIVE',
          last_login_at: new Date(Date.now() - 3_600_000).toISOString(),
          created_at: '2025-01-05T00:00:00Z',
          mfa_enrolled: false,
          grants: [
            {
              grant_id: '018f3c2a-0014-7e90-9c2d-000000000014',
              role_code: 'DISTRICT_APPROVER',
              role_name: {
                si: 'දිස්ත්‍රික් අනුමත කරන්නා',
                ta: 'மாவட்ட அனுமதியாளர்',
                en: 'District approver',
              },
              scope_type: 'DISTRICT',
              scope_code: 'LK-11',
            },
          ],
          scopes: ['disbursement:release', 'entitlement:approve_district', 'ledger:read'],
        },
      ],
    },
    {
      match: 'admin/roles',
      body: [
        {
          id: '018f3c2a-0015-7e90-9c2d-000000000015',
          code: 'DISTRICT_APPROVER',
          name: {
            si: 'දිස්ත්‍රික් අනුමත කරන්නා',
            ta: 'மாவட்ட அனுமதியாளர்',
            en: 'District approver',
          },
          scopes: ['disbursement:release', 'entitlement:approve_district', 'ledger:read'],
          grants_human_gate: true,
        },
      ],
    },
    { match: 'admin/gn-divisions', body: [] },
    { match: 'admin/households', body: [] },
    { match: 'cost-schedules', body: [] },
    {
      match: 'anomalies',
      body: [
        {
          id: '018f3c2a-0016-7e90-9c2d-000000000016',
          subject_type: 'gn_division',
          subject_id: 'LK-11-03-045',
          detector: 'disbursement_rate_per_household',
          detector_version: 'anomaly-1',
          score: 0.81,
          rationale: {
            pattern_summary:
              'Disbursements in this division are running above the district median for the same damage category.',
            innocent_explanations: [
              'A single severe flood event concentrated in one low-lying part of the division.',
              'A backlog cleared in one week after the assessment team returned.',
            ],
            what_would_resolve_it: [
              'Compare against the assessment dates rather than the release dates.',
            ],
          },
          raised_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
          disposition: 'OPEN',
          disposed_by: null,
          disposed_at: null,
          disposition_note: null,
        },
      ],
    },
    {
      match: 'ledger',
      body: [
        {
          seq: 4117,
          id: '018f3c2a-0017-7e90-9c2d-000000000017',
          entry_type: 'DISBURSEMENT',
          amount_lkr_cents: 12_500_000,
          prev_hash: 'a'.repeat(64),
          entry_hash: 'b'.repeat(64),
          anchor_date: '2025-11-28',
          created_at: new Date().toISOString(),
        },
      ],
    },
    { match: 'grievances', body: [] },
    { match: 'assessments', body: [] },
    { match: 'review-queue', body: [] },
    { match: 'disbursements', body: [] },
    { match: 'audit', body: [] },
  ];
}

/** What the browser reports about a rendered page. Serialisable, so it crosses cleanly. */
interface LayoutReport {
  readonly documentOverflowPx: number;
  readonly clipped: ReadonlyArray<{ selector: string; overflowPx: number; text: string }>;
}

/**
 * Measure overflow in the page.
 *
 * Runs in the browser because that is the only place the real font metrics exist — which is
 * the whole reason this suite is worth having alongside the design system's width model.
 */
async function measureLayout(page: Page): Promise<LayoutReport> {
  return page.evaluate(() => {
    const root = document.documentElement;
    const clipped: Array<{ selector: string; overflowPx: number; text: string }> = [];

    /** A short, human-findable name for an element. */
    const describe = (el: Element): string => {
      const id = el.id ? `#${el.id}` : '';
      const cls =
        typeof el.className === 'string' && el.className
          ? `.${el.className.trim().split(/\s+/).slice(0, 2).join('.')}`
          : '';
      return `${el.tagName.toLowerCase()}${id}${cls}`;
    };

    /**
     * Whether this element is visually hidden rather than laid out.
     *
     * The `sr-only` pattern is `width: 1px; height: 1px` plus a clip, so its content is
     * "overflowing" by construction - that is how it is hidden while staying in the
     * accessibility tree. Measuring by box size rather than by the clip property catches
     * every spelling of the pattern, including Tailwind's `clip-path` form: an element one
     * pixel wide is not a layout that can break.
     *
     * This was the whole of the suite's first run. Every route reported the skip link,
     * because the guard tested the *parent* for hiding and not the element itself.
     */
    const visuallyHidden = (el: Element): boolean =>
      el.clientWidth <= 1 || el.clientHeight <= 1;

    /** Whether this element or an ancestor scrolls on purpose. */
    const insideScrollable = (el: Element): boolean => {
      for (let node: Element | null = el; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.overflowX === 'auto' || style.overflowX === 'scroll') return true;
      }
      return false;
    };

    for (const el of Array.from(document.querySelectorAll('*'))) {
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') continue;
      if (style.overflowX !== 'hidden' && style.overflowX !== 'clip') continue;
      if (visuallyHidden(el)) continue;
      if (insideScrollable(el)) continue;

      // A pixel of slack: sub-pixel layout rounding is not an overflow bug, and asserting
      // on an exact equality here would make the suite fail on font-hinting differences
      // between machines - the very thing a pixel-baseline suite gets wrong.
      const overflowPx = el.scrollWidth - el.clientWidth;
      if (overflowPx <= 1) continue;

      // Only elements that actually carry text. A clipped decorative box is a styling
      // choice; a clipped division name is a person who cannot read where to go.
      const text = (el.textContent ?? '').trim();
      if (text.length === 0) continue;

      clipped.push({ selector: describe(el), overflowPx, text: text.slice(0, 60) });
    }

    return {
      documentOverflowPx: root.scrollWidth - root.clientWidth,
      clipped,
    };
  });
}

/**
 * The detector, checked against a deliberate overflow.
 *
 * A gate that has only ever passed is indistinguishable from a gate that cannot fail, and
 * this one is a hand-written DOM walk with several exclusions in it - each of which is a
 * chance to exclude the thing it is supposed to catch. That is not hypothetical here: the
 * first version tested the wrong node for visual hiding, and every route reported the skip
 * link. A guard that had been one clause broader would have reported nothing instead, and
 * the suite would have gone green while measuring nothing at all.
 *
 * So it is pointed at a known-bad element before it is trusted with the real ones.
 */
test('the overflow detector catches an overflow', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, everything());
  await page.goto('/en/login');
  await page.waitForLoadState('networkidle');

  await expect
    .poll(async () => (await measureLayout(page)).clipped.length)
    .toBe(0);

  // A box narrower than its own content, clipped - the shape a Tamil label takes when the
  // slot was sized in English.
  await page.evaluate(() => {
    const box = document.createElement('div');
    box.id = 'sarana-overflow-probe';
    box.style.cssText =
      'width:40px;overflow-x:hidden;white-space:nowrap;font-size:16px;position:relative';
    box.textContent = 'இது மிக நீளமான ஒரு தமிழ் சொற்றொடர் ஆகும்';
    document.body.appendChild(box);
  });

  const caught = await measureLayout(page);
  expect(
    caught.clipped.map((entry) => entry.selector),
    'the detector must report an element whose content is wider than its clipped box',
  ).toContain('div#sarana-overflow-probe');

  await page.evaluate(() => document.getElementById('sarana-overflow-probe')?.remove());
  expect((await measureLayout(page)).clipped).toEqual([]);
});

test.describe('every route, in three scripts, without overflow', () => {
  for (const route of ROUTES) {
    test(`${route} fits`, async ({ page }) => {
      await signInAs(page);
      await scriptGateway(page, everything());

      for (const locale of LOCALES) {
        await page.goto(`/${locale}${route}`);
        // Settle before measuring. A skeleton fits every layout, so measuring one would
        // pass while the populated screen overflowed.
        await page.waitForLoadState('networkidle');

        const report = await measureLayout(page);

        expect(
          report.documentOverflowPx,
          `${route} [${locale}] scrolls horizontally by ${report.documentOverflowPx}px. ` +
            'A console that scrolls sideways loses a column off the right edge on the ' +
            'hardware an operations room actually has.',
        ).toBeLessThanOrEqual(1);

        expect(
          report.clipped,
          `${route} [${locale}] clips text in ${report.clipped.length} element(s):\n` +
            report.clipped
              .map((c) => `    ${c.selector} +${c.overflowPx}px — "${c.text}"`)
              .join('\n'),
        ).toEqual([]);
      }
    });
  }
});
