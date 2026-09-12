"""The eight detectors. Deterministic, independently tested, and each rules something out.

Every detector obeys three rules, and they are the reason this agent is allowed to exist.

**It groups by GN division, never by person.** Not by assessor, not by approver, not by any
proxy for one. `Assessment` carries no officer field at all, so this is enforced by the
absence of the data rather than by anybody's discipline.

**It compares a division against its own forecast, never against its peers.** See
`normalisation`. A division that was hit hardest should look like a division that was hit
hardest.

**It names what it ruled out.** Every signal carries the innocent explanations that were
checked before it fired, and `Signal.actionable` is False without them. Build file 17: a
flag that does not show what was ruled out is not actionable and gets suppressed. A reviewer
opening a flag with no ruled-out list starts from zero, and a flag that costs more to review
than it saves is a flag that trains people to close flags unread.

## `confirmation_gap` is the one to read twice

It is the most valuable detector and the most easily misread. A division at 40% confirmation
and 35% cell coverage is a **coverage problem**: those households were never reachable to
confirm anything. A division at 40% confirmation and 95% coverage is a question worth asking.

Firing on the first would flag the poorest-connected divisions in the country for being
poorly connected — which is both wrong and exactly backwards, since those are the places
already least well served. So the coverage join happens before the comparison, not after.
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Final

import structlog

from agent_svc.agents.ledger_anomaly.normalisation import DivisionProfile
from agent_svc.agents.ledger_anomaly.ports import Evidence, Signal

_log = structlog.get_logger(__name__)

DETECTOR_VERSION: Final = "rule-v1"

# Cell coverage at or below which a low confirmation rate is a coverage problem and nothing
# else. Generous on purpose: the cost of not firing is a missed question, and the cost of
# firing is a flag against a division for having no signal.
COVERAGE_EXPLAINS_BELOW_PCT: Final = 70.0

# Confirmation below this is worth asking about - in a division that actually has coverage.
LOW_CONFIRMATION: Final = 0.60

# How many times the district median an approval speed has to beat before it is a question.
APPROVAL_SPEED_MULTIPLE: Final = 6.0

# The floor under a median comparison. A district median of half a minute makes every
# division "six times faster" on rounding alone.
MIN_MEDIAN_MINUTES: Final = 5.0

# Assessments in one division in one hour, as a multiple of that division's expected total,
# before the burst is a question. A survey team surging into a division is the ordinary
# explanation and it is checked first.
BURST_MULTIPLE: Final = 0.5

# How many assessments must share one evidence hash before it is a question. Two is a shared
# wall; four is a question.
EVIDENCE_REUSE_THRESHOLD: Final = 4

# How far outside its claimed division an assessment's coordinate can sit before it counts.
# Wide, because a boundary household with a poor fix is the ordinary case.
GEO_TOLERANCE_DEG: Final = 0.05

# The share of a division's assessments that must be geo-implausible before it is a signal.
# One is a bad fix; a third is a pattern.
GEO_SHARE: Final = 0.33

# How far a category mix can diverge from what the housing stock suggests. Loose: housing
# stock is a weak predictor and this detector is the most likely of the eight to be a false
# positive, which is why its score is capped low.
CATEGORY_DRIFT_TOLERANCE: Final = 0.45


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def value_distribution(profile: DivisionProfile) -> Signal | None:
    """Assessment values clustering at total loss, beyond what the forecast expected.

    Innocent explanation checked first: **genuine total losses in a severe division.** At
    `impact_class 4` the forecast expects 70% total loss, so a division producing that is
    producing what was predicted and never reaches this detector's threshold.
    """
    observed = profile.total_loss_share
    expected = profile.expectation.expected_total_loss_share
    if observed <= expected * 1.5 or observed - expected < 0.2:
        # Two conditions, both needed. The ratio alone flags a division that went from 2% to
        # 4%; the absolute gap alone flags one that went from 60% to 80% in a severe
        # division where that is ordinary.
        return None

    return Signal(
        detector="value_distribution",
        gn_division_code=profile.gn_division_code,
        score=_clamp((observed - expected) / max(0.2, 1.0 - expected)),
        evidence=[
            Evidence(
                label="total_loss_share",
                value=round(observed, 3),
                compared_with=round(expected, 3),
                note="share of assessments in the categories that write off a dwelling",
            ),
            Evidence(
                label="impact_class",
                value=profile.expectation.impact_class,
                note="what the forecast predicted for this division",
            ),
        ],
        ruled_out=[
            f"genuine total losses in a severe division: the forecast put this division at "
            f"impact class {profile.expectation.impact_class}, where "
            f"{expected:.0%} total loss is expected. The observed share is above that.",
        ],
    )


def temporal_burst(profile: DivisionProfile) -> Signal | None:
    """More assessments in one hour than the division was expected to produce in total.

    Innocent explanation checked first: **a survey team surged into the division.** That is
    the ordinary cause and it is indistinguishable from here, so the ruled-out line says so
    plainly and points the reviewer at the deployment record rather than at a person.
    """
    if not profile.assessments:
        return None

    by_hour = Counter(
        item.assessed_at.replace(minute=0, second=0, microsecond=0) for item in profile.assessments
    )
    hour, peak = by_hour.most_common(1)[0]
    threshold = profile.expectation.expected_claims * BURST_MULTIPLE
    if threshold <= 0 or peak <= threshold:
        return None

    return Signal(
        detector="temporal_burst",
        gn_division_code=profile.gn_division_code,
        score=_clamp((peak - threshold) / max(threshold, 1.0)),
        evidence=[
            Evidence(
                label="assessments_in_peak_hour",
                value=peak,
                compared_with=round(threshold, 1),
                note=f"hour beginning {hour.isoformat()}",
            ),
            Evidence(
                label="expected_claims_for_the_whole_event",
                value=round(profile.expectation.expected_claims, 1),
            ),
        ],
        ruled_out=[
            "a survey team surged into the division: check the deployment record for that "
            "hour before anything else. A team of six working a morning produces exactly "
            "this shape, and it is the most common cause.",
            f"the forecast expected {profile.expectation.expected_claims:.0f} claims for "
            "the entire event, so the peak hour alone exceeds it.",
        ],
    )


def duplicate_household(profile: DivisionProfile) -> Signal | None:
    """One household with several overlapping claims in the same category.

    Innocent explanation checked first: **a legitimate multi-category claim.** A household
    that lost its house, its tools and its livestock has three claims and should. So this
    only counts repeats *within* one category, which is the shape that is not explained by
    a household losing several different things.
    """
    per_household: dict[tuple[str, str], int] = Counter(
        (item.household_id, item.category) for item in profile.assessments
    )
    repeats = {key: count for key, count in per_household.items() if count > 1}
    if not repeats:
        return None

    return Signal(
        detector="duplicate_household",
        gn_division_code=profile.gn_division_code,
        score=_clamp(len(repeats) / max(1, profile.count) * 3),
        evidence=[
            Evidence(
                label="households_with_repeated_claims_in_one_category",
                value=len(repeats),
                compared_with=profile.count,
            ),
            Evidence(
                label="categories_affected",
                value=", ".join(sorted({category for _, category in repeats})),
            ),
        ],
        ruled_out=[
            "a legitimate multi-category claim: only repeats within a single category are "
            "counted here, so a household that lost its house, its tools and its livestock "
            "does not appear.",
        ],
    )


def geo_implausible(profile: DivisionProfile) -> Signal | None:
    """Assessment coordinates well outside the division they claim.

    Innocent explanation checked first: **poor GPS accuracy, or a boundary household.** The
    tolerance is deliberately wide and a share of the division's assessments has to be
    affected before this fires, because one bad fix is a bad fix.

    The division centroid stands in for its boundary. `admin.gn_division` has geometry and
    this agent does not read it: a point-in-polygon test would be better and needs a port
    this agent does not have. The evidence says which was used, so a reviewer is not misled
    about the precision of the check.
    """
    located = [item for item in profile.assessments if item.lon is not None]
    if not located:
        return None

    centroid_lon = statistics.fmean(float(item.lon or 0.0) for item in located)
    centroid_lat = statistics.fmean(float(item.lat or 0.0) for item in located)
    outside = [
        item
        for item in located
        if abs(float(item.lon or 0.0) - centroid_lon) > GEO_TOLERANCE_DEG
        or abs(float(item.lat or 0.0) - centroid_lat) > GEO_TOLERANCE_DEG
    ]
    share = len(outside) / len(located)
    if share < GEO_SHARE:
        return None

    return Signal(
        detector="geo_implausible",
        gn_division_code=profile.gn_division_code,
        score=_clamp(share),
        evidence=[
            Evidence(
                label="assessments_far_from_the_division_cluster",
                value=len(outside),
                compared_with=len(located),
                note=f"more than {GEO_TOLERANCE_DEG} degrees from the observed centroid",
            ),
            Evidence(
                label="check_used",
                value="distance from the cluster centroid",
                note="not a point-in-polygon test against the division boundary; this is "
                "the weaker check and the reviewer should treat it as one",
            ),
        ],
        ruled_out=[
            "poor GPS accuracy or a boundary household: a wide tolerance is applied and a "
            "third of the division's assessments must be affected, so one bad fix does "
            "not reach this.",
        ],
    )


def evidence_reuse(profile: DivisionProfile) -> Signal | None:
    """One photograph appearing across several assessments.

    Innocent explanation checked first: **a shared wall or a shared building.** Two
    households in one building photograph the same collapsed wall, and that is ordinary.
    Four assessments sharing one image is the point at which it stops being a building.
    """
    hashes: Counter[str] = Counter(
        digest for item in profile.assessments for digest in item.evidence_hashes
    )
    reused = {
        digest: count for digest, count in hashes.items() if count >= EVIDENCE_REUSE_THRESHOLD
    }
    if not reused:
        return None

    worst = max(reused.values())
    return Signal(
        detector="evidence_reuse",
        gn_division_code=profile.gn_division_code,
        score=_clamp(worst / max(1, profile.count)),
        evidence=[
            Evidence(
                label="images_reused_across_assessments",
                value=len(reused),
                note=f"the most-reused appears in {worst} assessments",
            ),
            Evidence(label="assessments_in_division", value=profile.count),
        ],
        ruled_out=[
            "a shared wall or shared building: two or three assessments sharing an image "
            f"is ordinary and is not counted. The threshold is {EVIDENCE_REUSE_THRESHOLD}.",
        ],
    )


def category_drift(profile: DivisionProfile) -> Signal | None:
    """A category mix that does not match the division's housing stock.

    Innocent explanation checked first: **different housing stock in the division.** That is
    precisely what this reads, so the detector is only meaningful where the housing data
    exists - and it suppresses itself where it does not rather than guessing.

    Scored low by construction. Housing stock is a weak predictor of category mix and this
    is the detector most likely to produce a false positive, so it contributes a question
    rather than a conclusion.
    """
    if profile.context.permanent_housing_pct is None:
        return None

    permanent = profile.context.permanent_housing_pct / 100.0
    house_claims = sum(
        1 for item in profile.assessments if item.category in {"HOUSE_FULL", "HOUSE_PARTIAL"}
    )
    observed = house_claims / profile.count
    gap = abs(observed - permanent)
    if gap <= CATEGORY_DRIFT_TOLERANCE:
        return None

    return Signal(
        detector="category_drift",
        gn_division_code=profile.gn_division_code,
        # Capped: see the docstring. This detector never carries a flag on its own.
        score=_clamp(gap * 0.5),
        evidence=[
            Evidence(
                label="house_damage_share",
                value=round(observed, 3),
                compared_with=round(permanent, 3),
                note="against the division's share of permanent housing",
            ),
        ],
        ruled_out=[
            "different housing stock in the division: this detector reads the division's "
            "own permanent-housing share rather than a regional average, and suppresses "
            "itself entirely where that figure is unknown.",
        ],
    )


def approval_velocity(profile: DivisionProfile, *, district_median: float) -> Signal | None:
    """Approvals far faster than the district's own median.

    Innocent explanation checked first: **a genuine emergency batch with a directive.** A
    district secretary can order a batch approved at speed and that is a legitimate act, so
    the ruled-out line points the reviewer at the directive record.

    The district median rather than a national one, because approval speed is a function of
    how a district is staffed. And a floor under it, because a district that approves in
    thirty seconds makes every division "six times faster" on rounding.
    """
    times = [
        item.approval_minutes for item in profile.assessments if item.approval_minutes is not None
    ]
    if len(times) < 3:
        return None

    median = statistics.median(times)
    baseline = max(district_median, MIN_MEDIAN_MINUTES)
    if median * APPROVAL_SPEED_MULTIPLE > baseline:
        return None

    return Signal(
        detector="approval_velocity",
        gn_division_code=profile.gn_division_code,
        score=_clamp(1.0 - (median / baseline)),
        evidence=[
            Evidence(
                label="median_approval_minutes",
                value=round(median, 1),
                compared_with=round(baseline, 1),
                note="against this district's own median, not a national one",
            ),
            Evidence(label="approvals_measured", value=len(times)),
        ],
        ruled_out=[
            "a genuine emergency batch with a directive: check the district's directive "
            "record for the period before anything else. A secretary ordering a batch "
            "approved at speed produces exactly this shape and is a legitimate act.",
            "district staffing differences: the comparison is against this district's own "
            "median rather than a national figure.",
        ],
    )


def confirmation_gap(profile: DivisionProfile) -> Signal | None:
    """Few citizens confirming, in a division that actually has coverage to confirm from.

    **Read the module docstring before changing this one.** The coverage join happens first
    and it is the whole safeguard: a division at 40% confirmation and 35% coverage is a
    coverage problem, and firing on it would flag the least-connected divisions in the
    country for being least connected.

    Innocent explanation checked first, and it is the coverage. Where coverage is unknown
    this suppresses rather than assuming it is good — an unknown is not a green light.
    """
    rate = profile.confirmation_rate
    if rate is None or rate >= LOW_CONFIRMATION:
        return None

    coverage = profile.context.cell_coverage_pct
    if coverage is None:
        _log.info(
            "anomaly_confirmation_gap_suppressed",
            gn_division_code=profile.gn_division_code,
            reason="cell coverage is unknown, and an unknown is not a green light",
        )
        return None
    if coverage <= COVERAGE_EXPLAINS_BELOW_PCT:
        _log.info(
            "anomaly_confirmation_gap_explained_by_coverage",
            gn_division_code=profile.gn_division_code,
            confirmation_rate=round(rate, 3),
            cell_coverage_pct=coverage,
            impact="not flagged; these households were never reachable to confirm anything",
        )
        return None

    return Signal(
        detector="confirmation_gap",
        gn_division_code=profile.gn_division_code,
        score=_clamp((LOW_CONFIRMATION - rate) / LOW_CONFIRMATION),
        evidence=[
            Evidence(
                label="citizen_confirmation_rate",
                value=round(rate, 3),
                compared_with=LOW_CONFIRMATION,
            ),
            Evidence(
                label="cell_coverage_pct",
                value=coverage,
                note="joined before comparing; a low rate in a low-coverage division is a "
                "coverage problem and is not flagged",
            ),
        ],
        ruled_out=[
            f"poor cell coverage: this division is at {coverage:.0f}% coverage, above the "
            f"{COVERAGE_EXPLAINS_BELOW_PCT:.0f}% threshold at which a low confirmation rate "
            "is explained by households simply not being reachable.",
        ],
    )


def run_all(profiles: list[DivisionProfile]) -> list[Signal]:
    """Every detector over every normalisable division.

    A division that cannot be normalised produces no signals at all and the reason is
    logged. See `normalisation`: being blind there is the correct trade.
    """
    signals: list[Signal] = []
    district_medians = _district_medians(profiles)

    for profile in profiles:
        if not profile.normalisable:
            continue

        district = profile.context.gn_division_code.rsplit("-", 2)[0]
        found = [
            value_distribution(profile),
            temporal_burst(profile),
            duplicate_household(profile),
            geo_implausible(profile),
            evidence_reuse(profile),
            category_drift(profile),
            approval_velocity(
                profile, district_median=district_medians.get(district, MIN_MEDIAN_MINUTES)
            ),
            confirmation_gap(profile),
        ]
        signals.extend(signal for signal in found if signal is not None)

    _log.info(
        "anomaly_detectors_run",
        divisions=len(profiles),
        normalisable=sum(1 for profile in profiles if profile.normalisable),
        signals=len(signals),
        by_detector=dict(Counter(signal.detector for signal in signals)),
    )
    return signals


def _district_medians(profiles: list[DivisionProfile]) -> dict[str, float]:
    """Median approval time per district, for `approval_velocity`.

    Per district rather than nationally, because approval speed is a function of how a
    district is staffed, and comparing a well-staffed district against a stretched one
    would flag the well-staffed one for working quickly.
    """
    by_district: dict[str, list[float]] = {}
    for profile in profiles:
        district = profile.gn_division_code.rsplit("-", 2)[0]
        by_district.setdefault(district, []).extend(
            item.approval_minutes
            for item in profile.assessments
            if item.approval_minutes is not None
        )
    return {district: statistics.median(times) for district, times in by_district.items() if times}
