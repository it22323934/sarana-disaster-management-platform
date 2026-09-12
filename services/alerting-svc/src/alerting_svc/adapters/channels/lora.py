"""The LoRa mesh tier — a real adapter with a simulated transport.

There is no LoRa hardware. This models one: nodes per division, hop counts, per-hop loss,
store-and-forward delay, and batteries that run down over a multi-day event.

**Every receipt this produces carries `simulated=True`**, the console shows the tier with a
Simulated badge, and the demo script says the word out loud. The architecture is real - the
adapter interface, the delivery accounting, the coverage model are all exactly what a
hardware tier would plug into. The transport is fake, and saying so plainly is the
difference between a prototype and a claim that will be found out.

The simulation is deliberately pessimistic. A mesh model that flatters itself would make
the coverage picture optimistic, and the coverage picture is what tells an operator which
villages to send a vehicle to.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Final

import structlog

from alerting_svc.adapters.channels.base import (
    Channel,
    DeliveryStatus,
    Message,
    Receipt,
)

_log = structlog.get_logger(__name__)

CHANNEL: Final = "LORA"

# Probability one hop delivers, on a healthy node. Chosen low: LoRa in hilly, wet terrain
# is not a reliable link, and modelling it as one would produce a coverage map that lies.
BASE_HOP_SUCCESS: Final = 0.92

# Nodes are solar. Over a multi-day event under cloud, they degrade.
DAILY_BATTERY_DECAY: Final = 0.08
MIN_BATTERY: Final = 0.15


@dataclass(slots=True)
class MeshNode:
    """One simulated node covering one division."""

    gn_division_code: str
    hops_to_gateway: int = 2
    battery: float = 1.0

    def delivery_probability(self) -> float:
        """Compounded per-hop loss, scaled by how much charge is left.

        Every hop is a chance to lose the message, so probability falls off geometrically
        with distance from the gateway - which is the property that makes the mesh useful
        near a gateway and close to useless far from one, and the console should show
        that rather than an average.
        """
        healthy = BASE_HOP_SUCCESS**self.hops_to_gateway
        return healthy * max(self.battery, 0.0)

    def age(self, days: float) -> None:
        """Run the battery down. Solar nodes under storm cloud do not recharge."""
        self.battery = max(MIN_BATTERY, self.battery - DAILY_BATTERY_DECAY * days)


@dataclass(slots=True)
class SimulatedMesh(Channel):
    """A configurable node topology with store-and-forward behaviour."""

    nodes: dict[str, MeshNode] = field(default_factory=dict)
    name: str = CHANNEL
    simulated: bool = True
    seed: int | None = None
    _random: random.Random = field(default_factory=random.Random)

    def __post_init__(self) -> None:
        if self.seed is not None:
            # Seeded runs make the demo reproducible and the tests deterministic.

            self._random = random.Random(self.seed)  # noqa: S311

    def node_for(self, gn_division_code: str) -> MeshNode:
        """The node covering a division, created on first sight."""
        if gn_division_code not in self.nodes:
            self.nodes[gn_division_code] = MeshNode(
                gn_division_code=gn_division_code,
                # Divisions differ in how far they sit from a gateway; deriving it from the
                # code keeps one division's coverage stable between runs.
                hops_to_gateway=1 + (hash(gn_division_code) % 4),
            )
        return self.nodes[gn_division_code]

    def age_all(self, days: float) -> None:
        """Advance every node's battery. Called by the simulation harness."""
        for node in self.nodes.values():
            node.age(days)

    async def send(self, messages: list[Message]) -> list[Receipt]:
        """Attempt delivery over the modelled mesh.

        Failures are per-message and expected. This channel exists to reach people the
        cell network cannot, and it does so unreliably; a receipt saying UNKNOWN is the
        honest outcome for a hop that was not acknowledged.
        """
        receipts: list[Receipt] = []
        for message in messages:
            node = self.node_for(message.target.gn_division_code)
            probability = node.delivery_probability()
            delivered = self._random.random() < probability

            receipts.append(
                Receipt(
                    target_ref_hash=message.target.target_ref_hash,
                    channel=CHANNEL,
                    language=message.language,
                    status=DeliveryStatus.DELIVERED if delivered else DeliveryStatus.UNKNOWN,
                    provider_ref=f"mesh:{node.gn_division_code}:{node.hops_to_gateway}",
                    failure_reason=None
                    if delivered
                    else f"no hop acknowledgement after {node.hops_to_gateway} hops",
                    simulated=True,
                )
            )

        _log.info(
            "lora_fanout_simulated",
            messages=len(messages),
            delivered=sum(1 for r in receipts if r.status is DeliveryStatus.DELIVERED),
            simulated=True,
        )
        return receipts

    def coverage(self, gn_division_code: str) -> float:
        """Modelled reachability for one division, for `/coverage`."""
        return self.node_for(gn_division_code).delivery_probability()
