"""Fan-out, delivery proof, and the soft third gate.

The cases named in the build brief, plus the two rules that make the delivery record worth
having: never a percentage without a denominator, and unconfirmed never counted as
delivered.
"""

from __future__ import annotations

import pytest

from alerting_svc.adapters.channels.base import (
    ChannelResult,
    DeliveryStatus,
    Message,
    Receipt,
    Target,
    languages_for,
)
from alerting_svc.adapters.channels.lora import SimulatedMesh
from alerting_svc.adapters.channels.mock_gateways import (
    InAppChannel,
    ManualChannel,
    MockPushService,
    MockSmsGateway,
    MockUssdPush,
)
from alerting_svc.domain import delivery, templates

pytestmark = pytest.mark.asyncio(loop_scope="session")

BODY = {"si": "යන්න", "ta": "செல்", "en": "Move to higher ground"}


def targets(count: int, *, division: str = "LK-21-01-001", language: str | None = None):
    return [
        Target(
            target_ref_hash=f"hash-{division}-{index}",
            gn_division_code=division,
            preferred_language=language,
        )
        for index in range(count)
    ]


class _BrokenChannel:
    """A channel whose whole integration is down."""

    name = "SMS"
    simulated = True

    async def send(self, messages: list[Message]) -> list[Receipt]:
        raise RuntimeError("gateway credentials rejected")


class _AllFailingSms:
    """A channel that is up and failing every message."""

    name = "SMS"
    simulated = True

    async def send(self, messages: list[Message]) -> list[Receipt]:
        return [
            Receipt(
                target_ref_hash=message.target.target_ref_hash,
                channel="SMS",
                language=message.language,
                status=DeliveryStatus.FAILED,
                failure_reason="no route to handset",
                simulated=True,
            )
            for message in messages
        ]


# --------------------------------------------------------------------------------------
# Fan-out isolates failure
# --------------------------------------------------------------------------------------


async def test_one_channel_throwing_does_not_stop_the_others() -> None:
    """The case the brief names.

    Without `return_exceptions=True` in the gather, one adapter's exception cancels its
    siblings mid-send and the alert reaches fewer people because an unrelated integration
    was broken.
    """
    channels = [
        _BrokenChannel(),
        MockPushService(),
        InAppChannel(),
        SimulatedMesh(seed=1),
        MockUssdPush(),
        ManualChannel(),
    ]

    results = await delivery.fan_out(channels, targets(10), BODY)

    assert len(results) == 6
    broken = [result for result in results if result.failed_outright]
    assert [result.channel for result in broken] == ["SMS"]
    # Every other channel still produced receipts.
    assert all(result.receipts for result in results if not result.failed_outright)


async def test_a_failed_channel_is_named_in_the_summary() -> None:
    """An operator must be able to see that a tier was down, not infer it from counts."""
    results = await delivery.fan_out([_BrokenChannel(), MockPushService()], targets(5), BODY)

    summary = delivery.summarise(results, targets(5))

    assert summary.channels_failed == ["SMS"]


# --------------------------------------------------------------------------------------
# The delivery picture
# --------------------------------------------------------------------------------------


async def test_a_target_confirmed_on_any_channel_counts_once() -> None:
    """The denominator is people, not messages.

    Someone who got the SMS and the push has been warned once.
    """
    people = targets(10)
    results = await delivery.fan_out([MockSmsGateway(seed=7), MockPushService()], people, BODY)

    summary = delivery.summarise(results, people)

    assert summary.targeted == 10
    assert summary.confirmed <= 10


async def test_unconfirmed_is_never_counted_as_delivered() -> None:
    """USSD and the mesh report UNKNOWN. Rounding those up would produce a map that lies."""
    people = targets(20)
    results = await delivery.fan_out([MockUssdPush()], people, BODY)

    summary = delivery.summarise(results, people)

    assert summary.confirmed == 0
    assert summary.unconfirmed == 20


async def test_a_target_no_channel_reached_is_counted_as_no_channel() -> None:
    """Silent omission is the failure this catches."""
    people = targets(5)

    summary = delivery.summarise([], people)

    assert summary.no_channel == 5
    assert summary.confirmed == 0


def test_the_summary_never_reports_a_bare_percentage() -> None:
    """ "82% delivered" is unactionable. The sentence carries every denominator."""
    summary = delivery.DeliverySummary(
        targeted=11_480, confirmed=9_412, unconfirmed=1_203, failed=0, no_channel=865
    )

    sentence = summary.as_sentence()

    assert "9,412 of 11,480" in sentence
    assert "1,203 unconfirmed" in sentence
    assert "865 with no channel available" in sentence


def test_zero_targets_is_zero_coverage_not_complete_coverage() -> None:
    """An empty area must not report itself as fully warned."""
    summary = delivery.DeliverySummary(
        targeted=0, confirmed=0, unconfirmed=0, failed=0, no_channel=0
    )

    assert summary.confirmed_fraction == 0.0


# --------------------------------------------------------------------------------------
# Gaps: the operationally important endpoint
# --------------------------------------------------------------------------------------


async def test_gaps_identify_a_division_where_sms_failed_entirely() -> None:
    """The case the brief names."""
    people = targets(10, division="LK-21-01-001")

    results = await delivery.fan_out([_AllFailingSms()], people, BODY)
    found = delivery.gaps(results, people)

    assert [gap.gn_division_code for gap in found] == ["LK-21-01-001"]
    assert found[0].confirmed == 0


async def test_a_well_covered_division_is_not_reported_as_a_gap() -> None:
    people = targets(10, division="LK-21-01-002")

    results = await delivery.fan_out([MockPushService()], people, BODY)
    found = delivery.gaps(results, people)

    assert found == []


async def test_gaps_are_ordered_worst_first() -> None:
    """A dispatcher works down the list, so the worst division must be at the top."""
    bad = targets(10, division="LK-21-01-001")
    partial = targets(10, division="LK-21-01-002")

    results = [
        ChannelResult(
            channel="SMS",
            receipts=[
                Receipt(
                    target_ref_hash=target.target_ref_hash,
                    channel="SMS",
                    language="en",
                    status=DeliveryStatus.FAILED,
                )
                for target in bad
            ]
            + [
                Receipt(
                    target_ref_hash=target.target_ref_hash,
                    channel="SMS",
                    language="en",
                    status=DeliveryStatus.SENT if index < 5 else DeliveryStatus.FAILED,
                )
                for index, target in enumerate(partial)
            ],
        )
    ]

    found = delivery.gaps(results, bad + partial)

    assert [gap.gn_division_code for gap in found] == ["LK-21-01-001", "LK-21-01-002"]


def test_a_gap_states_its_own_denominator() -> None:
    gap = delivery.DivisionGap(gn_division_code="LK-21-01-001", targeted=120, confirmed=14)

    assert "14 of 120" in gap.as_sentence()


# --------------------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------------------


def test_a_dry_run_counts_without_sending_anything() -> None:
    """The case the brief names.

    `dry_run` is deliberately synchronous and takes no transport: it *cannot* send, rather
    than choosing not to.
    """
    result = delivery.dry_run(
        [MockSmsGateway(), MockPushService(), InAppChannel()], targets(1_000), cap=5_000
    )

    assert result.targeted == 1_000
    assert result.by_channel["SMS"] == 1_000
    # The app carries all three languages; SMS carries one.
    assert result.by_channel["APP"] == 3_000
    assert not result.exceeds_cap


def test_a_dry_run_flags_an_area_selection_that_blows_the_cap() -> None:
    """A misconfigured area targeting the whole country, caught before twenty million SMS."""
    result = delivery.dry_run([MockSmsGateway()], targets(50_000), cap=10_000)

    assert result.exceeds_cap


def test_a_dry_run_estimates_cost_and_sms_is_what_costs() -> None:
    sms_only = delivery.dry_run([MockSmsGateway()], targets(100), cap=10_000)
    push_only = delivery.dry_run([MockPushService()], targets(100), cap=10_000)

    assert sms_only.estimated_cost_lkr > 0
    assert push_only.estimated_cost_lkr == 0


# --------------------------------------------------------------------------------------
# Language routing
# --------------------------------------------------------------------------------------


def test_a_known_preference_is_sent_first() -> None:
    target = Target(target_ref_hash="h", gn_division_code="LK-21-01-001", preferred_language="ta")

    assert languages_for(target, "SMS") == ["ta"]


def test_sms_carries_one_language_and_the_app_carries_three() -> None:
    """A trilingual SMS is three segments, at triple the cost and the queue time."""
    target = Target(target_ref_hash="h", gn_division_code="LK-21-01-001")

    assert len(languages_for(target, "SMS")) == 1
    assert len(languages_for(target, "APP")) == 3


def test_an_unknown_preference_uses_the_divisions_languages() -> None:
    """Never the person's name. Inferring language from a name goes wrong in exactly the
    communities most likely to be missed."""
    target = Target(target_ref_hash="h", gn_division_code="LK-41-01-001")

    ordered = languages_for(target, "APP", division_languages={"LK-41-01-001": ["ta"]})

    assert ordered[0] == "ta"


# --------------------------------------------------------------------------------------
# The soft third gate
# --------------------------------------------------------------------------------------


def test_an_alert_built_only_from_a_template_needs_no_signoff() -> None:
    rendered = templates.render(
        {
            "si": "{gn_division_name} වෙත",
            "ta": "{gn_division_name} க்கு",
            "en": "to {gn_division_name}",
        },
        {"gn_division_name": "Kandy 1-1"},
    )

    assert not rendered.requires_signoff


def test_free_text_forces_a_signoff() -> None:
    """The case the brief names. Speed is available, but only through templates."""
    rendered = templates.render(
        {"si": "යන්න", "ta": "செல்", "en": "Move"},
        {},
        free_text={"en": "and bring your livestock"},
    )

    assert rendered.contains_free_text
    assert rendered.requires_signoff


def test_a_template_rendered_with_a_missing_parameter_is_refused() -> None:
    """An alert must never dispatch reading "evacuate to {shelter_name}"."""
    with pytest.raises(templates.TemplateInvalid, match="not supplied"):
        templates.render(
            {
                "si": "{shelter_name}",
                "ta": "{shelter_name}",
                "en": "{shelter_name}",
            },
            {},
        )


def test_every_language_is_substituted() -> None:
    rendered = templates.render(
        {
            "si": "{shelter_name} වෙත",
            "ta": "{shelter_name} க்கு",
            "en": "to {shelter_name}",
        },
        {"shelter_name": "Kandy Central School"},
    )

    for text in rendered.body.values():
        assert "Kandy Central School" in text
        assert "{" not in text


# --------------------------------------------------------------------------------------
# The mesh is honest about being simulated
# --------------------------------------------------------------------------------------


async def test_every_lora_receipt_is_marked_simulated() -> None:
    """The badge in the console reads this. It must never be inferred from the name."""
    mesh = SimulatedMesh(seed=3)

    results = await delivery.fan_out([mesh], targets(20), BODY)

    assert results[0].receipts
    assert all(receipt.simulated for receipt in results[0].receipts)


async def test_mesh_delivery_falls_off_with_distance_from_the_gateway() -> None:
    """The property that makes the mesh useful near a gateway and not far from one."""
    mesh = SimulatedMesh(seed=3)
    near = mesh.node_for("near")
    near.hops_to_gateway = 1
    far = mesh.node_for("far")
    far.hops_to_gateway = 6

    assert near.delivery_probability() > far.delivery_probability()


def test_mesh_coverage_degrades_as_batteries_run_down() -> None:
    """Solar nodes under storm cloud do not recharge, and the coverage map should say so."""
    mesh = SimulatedMesh(seed=3)
    before = mesh.coverage("LK-21-01-001")

    mesh.age_all(days=3)

    assert mesh.coverage("LK-21-01-001") < before
