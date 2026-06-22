"""
agents/congestion_simulator.py
────────────────────────────────
Artificial congestion injection for testing and live demos.
Plain helper class — owned and ticked by TrafficOptimizationAgent.

What it does
────────────
Every `interval_ticks` ticks it randomly selects a vehicle in the
simulation and calls slowDown() on it and its immediate spatial
neighbours. This produces a realistic-looking congestion cluster that
the TrafficOptimizationAgent will detect and attempt to resolve,
demonstrating the full detection → rerouting → alert pipeline without
needing a real incident to occur.

Public API
──────────
  tick(vehicles, step, agent) → list[AgentEvent]
      Called once per simulation step by TrafficOptimizationAgent.
      Returns events to include in the UDP broadcast.

  enabled : bool
      Set to False at runtime to pause injection without restarting.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

try:
    import traci
except ImportError:
    traci = None  # replaced at runtime by SUMO or patched in tests

if TYPE_CHECKING:
    from .base_agent import AgentEvent


class CongestionSimulator:

    # How slow to make affected vehicles (m/s)
    SLOWDOWN_SPEED_MS:   float = 0.3
    # For how many simulated seconds the slowdown lasts
    SLOWDOWN_DURATION_S: float = 45.0
    # Radius within which neighbours are also slowed (cm)
    NEIGHBOUR_RADIUS_CM: float = 6_000.0
    # Max neighbours to slow alongside the primary vehicle
    MAX_NEIGHBOURS:      int   = 6

    def __init__(
        self,
        enabled:        bool = False,
        interval_ticks: int  = 500,
    ):
        self.enabled           = enabled
        self.interval_ticks    = interval_ticks
        self._cooldown:    int = interval_ticks   # start with a full delay
        self._injection_count: int = 0

    # ── public ────────────────────────────────────────────────────────────────

    def tick(
        self,
        vehicles: list[dict],
        step:     int,
        agent,                  # TrafficOptimizationAgent instance for emit()
    ) -> list["AgentEvent"]:

        if not self.enabled:
            return []

        if self._cooldown > 0:
            self._cooldown -= 1
            return []

        if len(vehicles) < self.MAX_NEIGHBOURS + 1:
            return []

        # ── pick a random primary vehicle ─────────────────────────────────
        primary    = random.choice(vehicles)
        px         = float(primary["x"])
        py         = float(primary["y"])
        primary_id = str(primary["id"])

        # ── gather spatial neighbours ─────────────────────────────────────
        r2 = self.NEIGHBOUR_RADIUS_CM ** 2
        neighbours = [
            v for v in vehicles
            if str(v["id"]) != primary_id
            and (float(v["x"]) - px) ** 2 + (float(v["y"]) - py) ** 2 <= r2
        ]
        targets = [primary] + neighbours[: self.MAX_NEIGHBOURS]

        # ── apply slowDown via TraCI ──────────────────────────────────────
        slowed: list[str] = []
        try:
            active_ids = set(traci.vehicle.getIDList())
        except Exception as exc:
            print(f"[CongestionSimulator] getIDList failed: {exc}")
            return []

        for v in targets:
            vid = str(v["id"])
            if vid not in active_ids:
                continue
            try:
                traci.vehicle.slowDown(
                    vid,
                    self.SLOWDOWN_SPEED_MS,
                    self.SLOWDOWN_DURATION_S,
                )
                slowed.append(vid)
            except Exception as exc:
                print(f"[CongestionSimulator] slowDown({vid}) skipped: {exc}")

        self._cooldown = self.interval_ticks
        self._injection_count += 1

        if not slowed:
            return []

        slowed_set = set(slowed)
        slowed_veh = [v for v in vehicles if str(v["id"]) in slowed_set]
        cx = sum(float(v["x"]) for v in slowed_veh) / len(slowed_veh)
        cy = sum(float(v["y"]) for v in slowed_veh) / len(slowed_veh)

        return [agent.emit(
            type     = "congestion_simulated",
            msg      = (
                f"[Simulation #{self._injection_count}] "
                f"Artificial congestion injected — "
                f"{len(slowed)} vehicles slowed to "
                f"{self.SLOWDOWN_SPEED_MS} m/s for "
                f"{self.SLOWDOWN_DURATION_S:.0f}s"
            ),
            severity = "info",
            x=cx, y=cy,
            simulated_vehicle_ids = slowed,
            slowdown_speed_ms     = self.SLOWDOWN_SPEED_MS,
            duration_sec          = self.SLOWDOWN_DURATION_S,
            injection_number      = self._injection_count,
        )]
