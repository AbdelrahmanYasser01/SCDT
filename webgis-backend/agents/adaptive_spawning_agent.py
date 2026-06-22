"""
agents/adaptive_spawning_agent.py
─────────────────────────────────
Adaptive Vehicle Spawning Agent.

Monitors overall traffic density and spawns or removes vehicles
dynamically via TraCI to maintain a target density range.  Keeps
the simulation feeling alive for long durations rather than all
vehicles finishing their routes and disappearing.

Emitted event types
───────────────────
  "spawn"   — vehicle added to maintain minimum density
  "remove"  — vehicle removed to prevent overcrowding
  "density" — periodic density analytics snapshot

Constructor arguments (all have defaults)
─────────────────────────────────────────
  min_vehicles       : spawn when active count drops below this  (10)
  max_vehicles       : remove when active count exceeds this     (30)
  check_interval     : only evaluate every N ticks  (50 = ~1 s @ 50 Hz)
  spawn_batch_size   : vehicles to add per check cycle           (2)
  remove_batch_size  : vehicles to remove per check cycle        (1)
  analytics_interval : emit density analytics every N ticks      (250)
"""

from __future__ import annotations

import random
import logging
from typing import Any
from .base_agent import BaseAgent, AgentEvent

log = logging.getLogger(__name__)

# TraCI is loaded lazily — same pattern used by sumo_simulator.py
traci: Any = None


def _import_traci() -> None:
    global traci
    if traci is None:
        import traci as _traci  # type: ignore[import-not-found]
        traci = _traci


class AdaptiveSpawningAgent(BaseAgent):

    def __init__(
        self,
        min_vehicles:       int = 10,
        max_vehicles:       int = 30,
        check_interval:     int = 50,       # ticks (~1 s at 50 Hz)
        spawn_batch_size:   int = 2,
        remove_batch_size:  int = 1,
        analytics_interval: int = 250,      # ~5 s at 50 Hz
    ):
        super().__init__(name="AdaptiveSpawningAgent")
        self.min_vehicles       = min_vehicles
        self.max_vehicles       = max_vehicles
        self.check_interval     = check_interval
        self.spawn_batch_size   = spawn_batch_size
        self.remove_batch_size  = remove_batch_size
        self.analytics_interval = analytics_interval

        # internal state
        self._spawn_counter: int = 0           # monotonic ID suffix
        self._total_spawned: int = 0
        self._total_removed: int = 0
        self._route_ids: list[str] = []        # cached at first use
        self._density_history: list[int] = []  # rolling vehicle counts
        self._known_vehicles: set[str] = set() # track all seen vehicles

        # Set by set_density_target() — triggers a one-shot 'density_updated' event
        self._pending_target_event: dict | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        super().on_start()
        _import_traci()
        log.info(
            "[%s] density target: %d–%d vehicles, "
            "check every %d ticks, spawn=%d remove=%d per cycle",
            self.name, self.min_vehicles, self.max_vehicles,
            self.check_interval, self.spawn_batch_size,
            self.remove_batch_size,
        )

    def on_stop(self) -> None:
        avg: float = (sum(self._density_history) / len(self._density_history)
                      if self._density_history else 0.0)
        print(
            f"[{self.name}] summary — "
            f"spawned={self._total_spawned}, "
            f"removed={self._total_removed}, "
            f"avg_density={avg:.1f}"
        )
        super().on_stop()

    # ── runtime target update (called from the sim thread) ────────────────────

    def set_density_target(
        self,
        min_vehicles: int | None = None,
        max_vehicles: int | None = None,
    ) -> dict:
        """Update the min/max density targets at runtime.

        Called by sumo_simulator._on_density_command() when the LangGraph
        orchestrator classifies a user query as 'density' intent.

        Returns a dict summarising the applied change so the caller can
        log/emit a confirmation event.

        Safety constraints
        ------------------
        - min must be >= 1 and < max
        - max is capped at 500 (prevents accidental SUMO overload)
        - If only one is provided the other stays unchanged
        """
        old_min, old_max = self.min_vehicles, self.max_vehicles
        changed = False

        if min_vehicles is not None:
            min_vehicles = max(1, int(min_vehicles))
            self.min_vehicles = min_vehicles
            changed = True

        if max_vehicles is not None:
            max_vehicles = min(500, max(self.min_vehicles + 1, int(max_vehicles)))
            self.max_vehicles = max_vehicles
            changed = True

        # Guard: min must always be < max after both are applied
        if self.min_vehicles >= self.max_vehicles:
            self.min_vehicles = max(1, self.max_vehicles - 1)

        result = {
            "changed": changed,
            "old_min": old_min,
            "old_max": old_max,
            "new_min": self.min_vehicles,
            "new_max": self.max_vehicles,
        }

        if changed:
            log.info(
                "[%s] density target updated: %d–%d → %d–%d",
                self.name, old_min, old_max,
                self.min_vehicles, self.max_vehicles,
            )
            # Stash so process() emits the confirmation event next tick
            self._pending_target_event = result

        return result

    # ── main hook ─────────────────────────────────────────────────────────────

    def process(
        self,
        vehicles: list[dict],
        sim_time: float,
        step:     int,
        *,
        context     = None,    # AgentContext — not used here
        prev_events = None,    # previous tick events — not used here
    ) -> list[AgentEvent]:

        events: list[AgentEvent] = []
        
        # Count all vehicles (no bounding-box filter — works for any SUMO network)
        current_count = len(vehicles)

        # Emit one-shot confirmation when a density target change was applied
        if self._pending_target_event is not None:
            ev = self._pending_target_event
            self._pending_target_event = None
            events.append(self.emit(
                type="density_updated",
                msg=(
                    f"Density target changed: {ev['old_min']}–{ev['old_max']} → "
                    f"{ev['new_min']}–{ev['new_max']}"
                ),
                severity="info",
                old_min=ev["old_min"],
                old_max=ev["old_max"],
                new_min=ev["new_min"],
                new_max=ev["new_max"],
                current_vehicles=current_count,
                sim_time=sim_time,
            ))

        # Record density for analytics
        self._density_history.append(current_count)

        # ── announce new vehicles (fixes missing initial cars in UE) ──────
        for v in vehicles:
            vid = str(v["id"])
            if vid not in self._known_vehicles:
                self._known_vehicles.add(vid)
                # Only emit if it's not a dyn_ vehicle (since dyn_ emits its own spawn event in _spawn_vehicle)
                if not vid.startswith("dyn_"):
                    events.append(self.emit(
                        type="spawn",
                        msg=f"Discovered initial vehicle {vid}",
                        vehicle=vid,
                        severity="info",
                        sim_time=sim_time,
                    ))

        # ── periodic density analytics ────────────────────────────────────
        if step % self.analytics_interval == 0 and step > 0:
            interval = self.analytics_interval
            window: list[int] = self._density_history[-interval:]
            avg: float = sum(window) / len(window) if window else 0.0
            mn: int = int(min(window)) if window else 0
            mx: int = int(max(window)) if window else 0
            events.append(self.emit(
                type="density",
                msg=f"Density: avg={avg:.1f} min={mn} max={mx} "
                    f"(target {self.min_vehicles}–{self.max_vehicles})",
                severity="info",
                avg_density=float(round(avg, 1)),
                min_density=mn,
                max_density=mx,
                current=current_count,
                total_spawned=self._total_spawned,
                total_removed=self._total_removed,
            ))

        # ── only adjust density every check_interval ticks ────────────────
        if step % self.check_interval != 0:
            return events

        # ── spawn vehicles if below minimum ───────────────────────────────
        if current_count < self.min_vehicles:
            deficit = self.min_vehicles - current_count
            to_spawn = min(deficit, self.spawn_batch_size)
            for _ in range(to_spawn):
                spawned = self._spawn_vehicle(sim_time)
                if spawned:
                    events.append(spawned)

        # ── remove vehicles if above maximum ──────────────────────────────
        elif current_count > self.max_vehicles:
            surplus = current_count - self.max_vehicles
            to_remove = min(surplus, self.remove_batch_size)
            # Pick from the spawned vehicles first to avoid killing
            # original scenario vehicles when possible
            active_ids = [str(v["id"]) for v in vehicles]
            spawned_active = [vid for vid in active_ids
                              if vid.startswith("dyn_")]
            # Fall back to any vehicle if no spawned ones remain
            pool = spawned_active if spawned_active else active_ids
            for _ in range(to_remove):
                if not pool:
                    break
                removed = self._remove_vehicle(pool, sim_time)
                if removed:
                    events.append(removed)

        return events

    # ── TraCI helpers ─────────────────────────────────────────────────────────

    def _get_route_ids(self) -> list[str]:
        """Cache the list of known route IDs from SUMO."""
        if not self._route_ids:
            try:
                # Filter out internal routes starting with '!'
                self._route_ids = [r for r in traci.route.getIDList() if not r.startswith("!")]
            except Exception:
                self._route_ids = []
        return self._route_ids

    def _spawn_vehicle(self, sim_time: float) -> AgentEvent | None:
        """Add a single vehicle into SUMO on a dynamically duplicated route."""
        self._spawn_counter += 1
        vid = f"dyn_{self._spawn_counter}"
        route_id = f"r_dyn_{self._spawn_counter}"

        try:
            # Clone a route from any active vehicle in the simulation
            active_vehicles = list(traci.vehicle.getIDList())
            if active_vehicles:
                sample_veh = random.choice(active_vehicles)
                edges = list(traci.vehicle.getRoute(sample_veh))
            else:
                # Fallback: pick a random existing route from the simulation
                all_routes = self._get_route_ids()
                if all_routes:
                    fallback_route = random.choice(all_routes)
                    edges = list(traci.route.getEdges(fallback_route))
                else:
                    log.warning("[%s] No routes available for spawning", self.name)
                    return None
            
            # Dynamically add the route to SUMO's database
            traci.route.add(route_id, edges)
            
            # Spawn the vehicle on this newly added route
            traci.vehicle.add(vid, route_id)
            self._total_spawned += 1
            log.debug("[%s] spawned %s on route %s", self.name, vid, route_id)
            return self.emit(
                type="spawn",
                msg=f"Spawned {vid} on route {route_id}",
                vehicle=vid,
                severity="info",
                route=route_id,
                sim_time=sim_time,
            )
        except Exception as exc:
            log.warning("[%s] spawn failed for %s: %s", self.name, vid, exc)
            return None

    def _remove_vehicle(
        self,
        pool: list[str],
        sim_time: float,
    ) -> AgentEvent | None:
        """Remove a random vehicle from the given pool."""
        vid = random.choice(pool)
        pool.remove(vid)  # avoid picking the same vehicle twice

        try:
            traci.vehicle.remove(vid)  # type: ignore[union-attr]
            self._total_removed += 1
            log.debug("[%s] removed %s", self.name, vid)
            return self.emit(
                type="remove",
                msg=f"Removed {vid} to reduce density",
                vehicle=vid,
                severity="info",
                sim_time=sim_time,
            )
        except Exception as exc:
            log.debug("[%s] remove failed for %s: %s", self.name, vid, exc)
            return None
