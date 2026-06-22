"""
agents/rerouting_engine.py
──────────────────────────
Handles vehicle rerouting via TraCI for the TrafficOptimizationAgent.
Plain helper class — owned by TrafficOptimizationAgent, not a BaseAgent.

How it works
────────────
SUMO's rerouteTraveltime() command recalculates each vehicle's route
using current travel-time estimates, which are automatically elevated on
congested edges. This naturally diverts vehicles to less-loaded paths
without requiring explicit alternative route computation.

Public API
──────────
  reroute(vehicle_ids) → list[str]
      Attempts to reroute each vehicle id in the list.
      Returns the ids that were successfully rerouted.
"""

from __future__ import annotations

try:
    import traci
except ImportError:
    traci = None  # replaced at runtime by SUMO or patched in tests


class ReroutingEngine:

    def __init__(self):
        pass

    # ── public ────────────────────────────────────────────────────────────────

    def reroute(self, vehicle_ids: list[str]) -> list[str]:
        """
        Reroute the given vehicles using SUMO's travel-time based rerouting.

        SUMO will automatically pick an alternative route that avoids
        congested edges (based on accumulated travel time data).
        Vehicles that have already reached their last edge, or that are
        not currently in the simulation, are silently skipped.

        Parameters
        ----------
        vehicle_ids : list of SUMO vehicle ID strings

        Returns
        -------
        list of IDs that were successfully rerouted
        """
        try:
            active = set(traci.vehicle.getIDList())
        except Exception as exc:
            print(f"[ReroutingEngine] getIDList failed: {exc}")
            return []

        rerouted: list[str] = []

        for vid in vehicle_ids:
            if vid not in active:
                continue
            if not self._has_remaining_route(vid):
                continue
            try:
                traci.vehicle.rerouteTraveltime(vid)
                rerouted.append(vid)
            except Exception as exc:
                print(f"[ReroutingEngine] rerouteTraveltime({vid}) skipped: {exc}")

        return rerouted

    # ── internal ──────────────────────────────────────────────────────────────

    def _has_remaining_route(self, vid: str) -> bool:
        """
        Returns True if the vehicle still has at least one edge remaining
        in its route beyond its current edge. Rerouting a vehicle on its
        last edge raises a TraCI error and accomplishes nothing.
        """
        try:
            route      = traci.vehicle.getRoute(vid)
            edge_index = traci.vehicle.getRouteIndex(vid)
            return edge_index < len(route) - 1
        except Exception:
            return False
