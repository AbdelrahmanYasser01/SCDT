"""
agents/context.py
─────────────────
Shared state for agent-to-agent coordination.

`AgentContext` is a small queryable registry that every agent gets a reference
to via `process(..., context=...)`. Agents READ from it to inform decisions
(e.g. "is there an active hazard near this zone?") and WRITE to it to broadcast
what they just did (e.g. "I added hazard X at edge E").

Combined with `prev_events` (each agent receives the previous tick's events),
this gives a clean feedback loop without coupling agents to each other directly.

Why one tick of delay
─────────────────────
Agents that read prev_events see what other agents did on tick N-1. That's
~20 ms at 50 Hz — well below human perception, and it removes any ordering
dependency between agents. An agent can be reordered, disabled, or replaced
without breaking another.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable


# ── Snapshots ──────────────────────────────────────────────────────────────────

@dataclass
class HazardSnapshot:
    """Lightweight view of a hazard, written by HazardAgent."""
    id:        str
    type:      str
    severity:  str
    responder: str
    edge:      str
    x:         float   # Unreal cm
    y:         float   # Unreal cm
    spawned_at_s:    float
    resolves_at_s:   float
    ev_arrived:      bool = False


@dataclass
class ZoneSnapshot:
    """Lightweight view of a congestion zone, written by TrafficOptimizationAgent."""
    id:            str
    cx:            float  # Unreal cm
    cy:            float  # Unreal cm
    severity:      str    # "info" | "warning" | "critical"
    vehicle_count: int
    avg_speed_cms: float
    ticks_active:  int
    is_urgent:     bool = False     # set True when zone overlaps an active hazard


# ── Context ────────────────────────────────────────────────────────────────────

@dataclass
class AgentContext:
    """Shared state and event log passed to every agent each tick.

    Holds two registries (hazards and zones) that agents publish to, plus
    helpers for spatial queries. The same instance lives for the entire sim —
    AgentManager updates `sim_time` / `step` each tick and snapshots events.
    """
    sim_time: float = 0.0
    step:     int   = 0

    active_hazards: dict[str, HazardSnapshot] = field(default_factory=dict)
    active_zones:   dict[str, ZoneSnapshot]   = field(default_factory=dict)

    # ── publish ────────────────────────────────────────────────────────────
    def upsert_hazard(self, snap: HazardSnapshot) -> None:
        self.active_hazards[snap.id] = snap

    def remove_hazard(self, hazard_id: str) -> None:
        self.active_hazards.pop(hazard_id, None)

    def upsert_zone(self, snap: ZoneSnapshot) -> None:
        self.active_zones[snap.id] = snap

    def remove_zone(self, zone_id: str) -> None:
        self.active_zones.pop(zone_id, None)

    # ── queries ────────────────────────────────────────────────────────────
    def hazards_near(self, x: float, y: float, radius_cm: float
                     ) -> list[HazardSnapshot]:
        """All active hazards whose location is within `radius_cm` of (x, y)."""
        r2 = radius_cm * radius_cm
        return [h for h in self.active_hazards.values()
                if (h.x - x) ** 2 + (h.y - y) ** 2 <= r2]

    def zones_near(self, x: float, y: float, radius_cm: float
                   ) -> list[ZoneSnapshot]:
        r2 = radius_cm * radius_cm
        return [z for z in self.active_zones.values()
                if (z.cx - x) ** 2 + (z.cy - y) ** 2 <= r2]

    # ── debug ──────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (f"<AgentContext t={self.sim_time:.1f} step={self.step} "
                f"hazards={len(self.active_hazards)} "
                f"zones={len(self.active_zones)}>")
