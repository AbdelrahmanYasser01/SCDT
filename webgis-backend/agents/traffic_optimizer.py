"""
agents/traffic_optimizer.py
───────────────────────────
Traffic Optimization Agent — detects congestion zones in the live vehicle
list and automatically reroutes vehicles via TraCI.
Also supports artificial congestion injection for demo / testing.

Features merged from two branches:
  • detection / reconciliation: sustained-slow ticks, edge bucketing,
    Jaccard zone matching, trend tracking, per-vehicle reroute cap,
    color tinting, reroute-effectiveness follow-up
  • cross-agent coordination (AgentContext): preemptive reroute when a
    HazardAgent emits hazard_alert; URGENT mode (60 % fraction, no
    cooldown) for zones that overlap an active hazard

Emitted event types
───────────────────
  "congestion_detected"     — a new congestion zone has been identified
  "congestion_resolved"     — a previously active zone has cleared
  "vehicles_rerouted"       — a batch of vehicles was given new routes
                              (reason: hazard_avoidance | hazard_zone_urgent
                              | congestion_relief)
  "congestion_simulated"    — an artificial slowdown was injected (test mode)
  "reroute_effectiveness"   — delayed measurement of a previous reroute's
                              impact on average zone speed
"""

from __future__ import annotations

import math
from dataclasses import dataclass

try:
    import traci
except ImportError:
    traci = None  # replaced at runtime by SUMO or patched in tests

from .base_agent          import BaseAgent, AgentEvent
from .context             import ZoneSnapshot
from .rerouting_engine    import ReroutingEngine
from .congestion_simulator import CongestionSimulator


# ── Internal zone record ──────────────────────────────────────────────────────

@dataclass
class _CongestionZone:
    """Tracks a single active congestion cluster across ticks."""
    cx:              float
    cy:              float
    vehicle_ids:     list[str]
    avg_speed_cms:   float
    ticks_active:    int  = 0
    action_cooldown: int  = 0
    last_action:     str  = ""
    # Historical / reconciliation metrics
    peak_severity_cms: float = 1e9   # smallest avg_speed_cms ever seen (lower = worse)
    ticks_worsening:    int   = 0
    ticks_clearing:     int   = 0

    def severity(self) -> str:
        if self.avg_speed_cms < 100:   # < 1 m/s — nearly stopped
            return "critical"
        if self.avg_speed_cms < 250:   # < 2.5 m/s — crawling
            return "warning"
        return "info"                  # slow but moving


# ── Agent ─────────────────────────────────────────────────────────────────────

class TrafficOptimizationAgent(BaseAgent):

    # When a zone overlaps an active hazard we reroute MORE aggressively and
    # skip the cooldown — these jams aren't going to clear by themselves.
    URGENT_REROUTE_FRACTION = 0.60
    HAZARD_PROXIMITY_CM     = 10_000.0   # 100 m

    def __init__(
        self,
        speed_threshold_cms:       float = 400.0,
        speed_threshold_ratio:     float = 0.25,
        density_radius_cm:         float = 8_000.0,
        min_vehicles:              int   = 4,
        action_cooldown_ticks:     int   = 100,
        sustained_slow_ticks:      int   = 15,
        simulate_congestion:       bool  = False,
        simulation_interval_ticks: int   = 500,
        reroute_fraction:          float = 0.33,
        anti_displacement_ratio:   float = 0.7,
    ):
        super().__init__(name="TrafficOptimizationAgent")

        self.speed_threshold        = speed_threshold_cms
        self.speed_threshold_ratio  = speed_threshold_ratio
        self.density_radius         = density_radius_cm
        self.min_vehicles           = min_vehicles
        self.cooldown_ticks         = action_cooldown_ticks
        self.sustained_slow_ticks   = sustained_slow_ticks
        self.reroute_fraction       = reroute_fraction
        self.anti_displacement_ratio = anti_displacement_ratio

        # Per-vehicle sustained-slowness counters (vid → consecutive slow ticks)
        self._slow_ticks: dict[str, int] = {}

        # ReroutingEngine — try the new ctor; fall back to the old one.
        try:
            self._rerouter = ReroutingEngine(anti_displacement_ratio=anti_displacement_ratio)
        except TypeError:
            self._rerouter = ReroutingEngine()

        self._simulator = CongestionSimulator(
            enabled=simulate_congestion,
            interval_ticks=simulation_interval_ticks,
        )

        # Per-vehicle reroute cap to prevent infinite yo-yo reroutes.
        self.per_vehicle_reroute_cap: int = 3
        self._vehicle_reroute_count: dict[str, int] = {}

        self._active_zones: list[_CongestionZone] = []

        # Visualisation — tint rerouted vehicles yellow for a few seconds.
        self.color_tint_duration_ticks: int = 500   # ~10 s @ 50 Hz
        self._tinted: dict[str, int] = {}
        self._original_colors: dict[str, tuple] = {}

        # Delayed effectiveness check.
        self.reroute_effectiveness_delay_ticks: int = 1500   # ~30 s @ 50 Hz
        self._pending_followups: list[dict] = []

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        super().on_start()

    def on_stop(self) -> None:
        print(
            f"[{self.name}] Shutdown — "
            f"{len(self._active_zones)} zone(s) still active."
        )
        super().on_stop()

    # ── main hook ─────────────────────────────────────────────────────────────

    def process(
        self,
        vehicles:    list[dict],
        sim_time:    float,
        step:        int,
        *,
        context     = None,    # AgentContext for cross-agent coordination
        prev_events = None,
    ) -> list[AgentEvent]:

        events: list[AgentEvent] = []

        # 0a. CROSS-AGENT REACTION — preemptive reroute on hazard alerts that
        #     were emitted on the previous tick.
        events.extend(self._react_to_peer_events(prev_events))

        # 0b. Revert color tints that have expired.
        self._tick_tints()

        # 0c. Emit any due reroute-effectiveness follow-ups.
        events.extend(self._tick_followups(step))

        # 1. Optionally inject artificial congestion for testing / demos.
        events.extend(self._simulator.tick(vehicles, step, self))

        # Clean up per-vehicle reroute counters for departed vehicles.
        active_ids = {str(v["id"]) for v in vehicles}
        self._vehicle_reroute_count = {
            k: v for k, v in self._vehicle_reroute_count.items() if k in active_ids
        }

        # 2. Detect congestion zones from the current vehicle list.
        detected = self._detect_zones(vehicles)

        # 3. Reconcile, escalating to URGENT mode for any zone that overlaps
        #    an active hazard (via the shared context).
        events.extend(self._reconcile(detected, step, context=context))

        return events

    # ── cross-agent reactions ─────────────────────────────────────────────────

    def _react_to_peer_events(self, prev_events) -> list[AgentEvent]:
        """Preemptive reroute when a hazard appeared on the previous tick.

        Scans every active vehicle's remaining route; any vehicle still routed
        through the hazard's destination edge is handed to ReroutingEngine so
        SUMO picks an alternative path BEFORE the vehicle hits the jam.
        Respects the same filters (no EVs, no buses, per-vehicle cap) as
        the regular congestion-relief path.
        """
        if not prev_events:
            return []

        events: list[AgentEvent] = []
        for evt in prev_events:
            if evt.type != "hazard_alert":
                continue
            dest_edge = evt.data.get("dest_edge") if evt.data else None
            if not dest_edge or traci is None:
                continue

            affected: list[str] = []
            try:
                for vid in traci.vehicle.getIDList():
                    if vid.startswith("EV_"):
                        continue
                    if self._vehicle_reroute_count.get(vid, 0) >= self.per_vehicle_reroute_cap:
                        continue
                    try:
                        vtype = traci.vehicle.getTypeID(vid).lower()
                        if any(k in vtype for k in ("bus", "emergency", "ambulance", "fire", "police")):
                            continue
                    except Exception:
                        pass
                    try:
                        route       = traci.vehicle.getRoute(vid)
                        edge_index  = traci.vehicle.getRouteIndex(vid)
                    except Exception:
                        continue
                    remaining = route[max(0, edge_index):]
                    if dest_edge in remaining:
                        affected.append(vid)
            except Exception as exc:
                print(f"[{self.name}] preemptive-reroute scan failed: {exc}")
                continue

            if not affected:
                continue

            # Reroute up to 50 % of the affected vehicles preemptively.
            to_reroute = affected[: max(1, len(affected) // 2)]
            rerouted = self._rerouter.reroute(to_reroute)
            if not rerouted:
                continue

            for vid in rerouted:
                self._vehicle_reroute_count[vid] = self._vehicle_reroute_count.get(vid, 0) + 1

            print(f"[{self.name}] HAZARD-AVOIDANCE | rerouted {len(rerouted)} of "
                  f"{len(affected)} vehicles routed through hazard edge {dest_edge}")

            events.append(self.emit(
                type     = "vehicles_rerouted",
                msg      = (f"Preemptively rerouted {len(rerouted)} vehicles "
                            f"away from hazard at {dest_edge}"),
                severity = "info",
                rerouted_count = len(rerouted),
                rerouted_ids   = rerouted,
                reason         = "hazard_avoidance",
                hazard_id      = evt.data.get("hazard_id") if evt.data else None,
                dest_edge      = dest_edge,
            ))
        return events

    # ── tint + followup helpers ───────────────────────────────────────────────

    def _tick_tints(self) -> None:
        """Decrement and revert any active color tints on rerouted vehicles."""
        if traci is None or not self._tinted:
            return
        to_revert = []
        for vid in list(self._tinted.keys()):
            self._tinted[vid] -= 1
            if self._tinted[vid] <= 0:
                to_revert.append(vid)
        for vid in to_revert:
            try:
                orig = self._original_colors.get(vid)
                if orig is not None:
                    traci.vehicle.setColor(vid, orig)
            except Exception:
                pass
            self._tinted.pop(vid, None)
            self._original_colors.pop(vid, None)

    def _tick_followups(self, step: int) -> list[AgentEvent]:
        """Emit reroute_effectiveness events that have come due."""
        events: list[AgentEvent] = []
        for f in list(self._pending_followups):
            if f["due_step"] > step:
                continue
            vids = f.get("vehicle_ids", [])
            speeds = []
            for vid in vids:
                try:
                    speeds.append(traci.vehicle.getSpeed(vid) * 100.0)   # m/s → cm/s
                except Exception:
                    continue
            after_avg = round(sum(speeds) / len(speeds), 1) if speeds else None
            events.append(self.emit(
                type     = "reroute_effectiveness",
                msg      = (f"Reroute effectiveness: before={f.get('before_avg')} cms, "
                            f"after={after_avg} cms"),
                severity = "info",
                x=f.get("x"), y=f.get("y"),
                zone_avg_speed_before = f.get("before_avg"),
                zone_avg_speed_after  = after_avg,
                vehicle_ids           = vids,
            ))
            self._pending_followups.remove(f)
        return events

    # ── zone detection ────────────────────────────────────────────────────────

    def _detect_zones(self, vehicles: list[dict]) -> list[_CongestionZone]:
        """Clusters slow vehicles by SUMO edge.

        A vehicle is "slow" if its speed is below `speed_threshold_ratio` of
        the road's max speed (or the absolute `speed_threshold_cms` fallback)
        for `sustained_slow_ticks` consecutive ticks. This rejects momentary
        stops at lights / pedestrian crossings.

        Slow vehicles are then bucketed by their current SUMO edge so a
        cluster always belongs to one road — no merging of stacked
        bridge/tunnel vehicles 80 m apart vertically.
        """
        slow: list[tuple[float, float, str, float]] = []
        for v in vehicles:
            vid       = str(v["id"])
            speed_cms = float(v.get("speed", 0.0))

            try:
                lane         = traci.vehicle.getLaneID(vid)
                lane_max_ms  = traci.lane.getMaxSpeed(lane)
                threshold    = lane_max_ms * 100.0 * self.speed_threshold_ratio
            except Exception:
                threshold = self.speed_threshold

            if speed_cms < threshold:
                self._slow_ticks[vid] = self._slow_ticks.get(vid, 0) + 1
            else:
                self._slow_ticks.pop(vid, None)

            if self._slow_ticks.get(vid, 0) >= self.sustained_slow_ticks:
                slow.append((float(v["x"]), float(v["y"]), vid, speed_cms))

        if len(slow) < self.min_vehicles:
            return []

        edge_buckets: dict[str, list[tuple[float, float, str, float]]] = {}
        for x, y, vid, spd in slow:
            try:
                edge = traci.vehicle.getRoadID(vid)
            except Exception:
                edge = ""
            edge_buckets.setdefault(edge, []).append((x, y, vid, spd))

        zones: list[_CongestionZone] = []
        for edge, members in edge_buckets.items():
            if len(members) < self.min_vehicles:
                continue
            cx        = sum(p[0] for p in members) / len(members)
            cy        = sum(p[1] for p in members) / len(members)
            avg_speed = sum(p[3] for p in members) / len(members)
            zones.append(_CongestionZone(
                cx=cx, cy=cy,
                vehicle_ids=[p[2] for p in members],
                avg_speed_cms=avg_speed,
            ))
        return zones

    # ── zone reconciliation ───────────────────────────────────────────────────

    def _reconcile(
        self,
        detected: list[_CongestionZone],
        step:     int,
        context = None,
    ) -> list[AgentEvent]:
        """
        Matches newly detected zones to the active registry.
          - New zones   → emit detection event, reroute immediately.
          - Known zones → update, reroute again once cooldown expires.
          - Gone zones  → emit resolved event, remove from registry.

        When a zone is inside `HAZARD_PROXIMITY_CM` of an active hazard
        (via the shared context), it is marked URGENT — reroutes use a
        larger fraction (60 %) and the cooldown is bypassed.
        """
        events:      list[AgentEvent] = []
        match_radius = self.density_radius * 1.5
        matched_idx  = set()

        for zone in detected:
            # Jaccard match first — more stable than centroid for drifting zones.
            best_i, best_score = None, 0.0
            for i, active in enumerate(self._active_zones):
                s1, s2 = set(zone.vehicle_ids), set(active.vehicle_ids)
                if not s1 or not s2:
                    continue
                inter = len(s1 & s2)
                union = len(s1 | s2)
                jaccard = inter / union if union else 0.0
                if jaccard > best_score:
                    best_score, best_i = jaccard, i

            if best_score < 0.3:
                best_i, best_d = None, match_radius
                for i, active in enumerate(self._active_zones):
                    d = math.dist((zone.cx, zone.cy), (active.cx, active.cy))
                    if d < best_d:
                        best_d, best_i = d, i

            # CROSS-AGENT bit: is this zone overlapping a known active hazard?
            is_urgent = self._zone_is_near_hazard(zone, context)

            if best_i is not None:
                # ── update existing zone ──────────────────────────────────
                active = self._active_zones[best_i]
                active.cx = zone.cx
                active.cy = zone.cy
                active.vehicle_ids = zone.vehicle_ids
                matched_idx.add(best_i)

                prev_avg = active.avg_speed_cms
                new_avg  = zone.avg_speed_cms
                active.avg_speed_cms = new_avg
                active.ticks_active += 1
                if new_avg < active.peak_severity_cms:
                    active.peak_severity_cms = new_avg
                if new_avg < prev_avg:
                    active.ticks_worsening += 1
                    active.ticks_clearing = 0
                elif new_avg > prev_avg:
                    active.ticks_clearing += 1
                    active.ticks_worsening = 0

                # Urgent zones bypass the cooldown completely.
                if is_urgent or active.action_cooldown <= 0:
                    action_events = self._optimize(active, step, urgent=is_urgent)
                    events.extend(action_events)
                    if action_events:
                        active.action_cooldown = 0 if is_urgent else self.cooldown_ticks
                else:
                    active.action_cooldown -= 1

                self._publish_zone(active, is_urgent, context, zone_id=f"Z{best_i}")

            else:
                # ── brand-new zone ────────────────────────────────────────
                zone.ticks_active      = 1
                zone.peak_severity_cms = zone.avg_speed_cms
                zone.ticks_worsening   = 0
                zone.ticks_clearing    = 0
                self._active_zones.append(zone)
                idx = len(self._active_zones) - 1
                matched_idx.add(idx)

                tag = "HAZARD-LINKED " if is_urgent else ""
                print(
                    f"[{self.name}] {tag}CONGESTION DETECTED | "
                    f"{len(zone.vehicle_ids)} vehicles | "
                    f"avg speed {zone.avg_speed_cms / 100:.1f} m/s | "
                    f"severity={zone.severity()} | "
                    f"centroid=({zone.cx:.0f}, {zone.cy:.0f})"
                )

                events.append(self.emit(
                    type     = "congestion_detected",
                    msg      = (
                        f"{'Hazard-linked c' if is_urgent else 'C'}ongestion zone — "
                        f"{len(zone.vehicle_ids)} vehicles, "
                        f"avg speed {zone.avg_speed_cms / 100:.1f} m/s"
                    ),
                    severity = zone.severity(),
                    x=zone.cx, y=zone.cy,
                    vehicle_count      = len(zone.vehicle_ids),
                    avg_speed_cms      = round(zone.avg_speed_cms, 1),
                    peak_severity_cms  = round(zone.peak_severity_cms, 1),
                    ticks_worsening    = zone.ticks_worsening,
                    ticks_clearing     = zone.ticks_clearing,
                    vehicle_ids        = zone.vehicle_ids,
                    is_hazard_induced  = is_urgent,
                ))

                action_events = self._optimize(zone, step, urgent=is_urgent)
                events.extend(action_events)
                if action_events:
                    zone.action_cooldown = 0 if is_urgent else self.cooldown_ticks

                self._publish_zone(zone, is_urgent, context, zone_id=f"Z{idx}")

        # ── resolve zones that have cleared ──────────────────────────────
        still_active = []
        for i, active in enumerate(self._active_zones):
            if i in matched_idx:
                still_active.append(active)
            else:
                print(
                    f"[{self.name}] CONGESTION RESOLVED | "
                    f"zone cleared after {active.ticks_active} ticks "
                    f"({active.ticks_active / 50:.1f}s) | "
                    f"centroid=({active.cx:.0f}, {active.cy:.0f})"
                )
                events.append(self.emit(
                    type     = "congestion_resolved",
                    msg      = (
                        f"Congestion cleared after {active.ticks_active} ticks "
                        f"({active.ticks_active / 50:.1f}s)"
                    ),
                    severity = "info",
                    x=active.cx, y=active.cy,
                    ticks_active      = active.ticks_active,
                    peak_severity_cms = round(active.peak_severity_cms, 1),
                    ticks_worsening   = active.ticks_worsening,
                    ticks_clearing    = active.ticks_clearing,
                ))
                if context is not None:
                    context.remove_zone(f"Z{i}")

        self._active_zones = still_active
        return events

    def _zone_is_near_hazard(self, zone: _CongestionZone, context) -> bool:
        """True if any active hazard is within HAZARD_PROXIMITY_CM of the zone."""
        if context is None or not context.active_hazards:
            return False
        return bool(context.hazards_near(zone.cx, zone.cy, self.HAZARD_PROXIMITY_CM))

    def _publish_zone(
        self,
        zone:       _CongestionZone,
        is_urgent:  bool,
        context,
        zone_id:    str,
    ) -> None:
        if context is None:
            return
        context.upsert_zone(ZoneSnapshot(
            id            = zone_id,
            cx            = zone.cx,
            cy            = zone.cy,
            severity      = zone.severity(),
            vehicle_count = len(zone.vehicle_ids),
            avg_speed_cms = zone.avg_speed_cms,
            ticks_active  = zone.ticks_active,
            is_urgent     = is_urgent,
        ))

    # ── optimization ──────────────────────────────────────────────────────────

    def _optimize(
        self,
        zone:    _CongestionZone,
        step:    int,
        urgent:  bool = False,
    ) -> list[AgentEvent]:
        """Reroutes a fraction of the congested vehicles.

        Also:
          • Applies a yellow tint to rerouted vehicles (UX).
          • Schedules a `reroute_effectiveness` follow-up emission.
          • Respects per-vehicle reroute cap + skips emergency/bus types.
          • When `urgent=True` (zone overlaps a hazard), uses 60 % fraction
            instead of the standard 33 %.
        """
        frac = self.URGENT_REROUTE_FRACTION if urgent else self.reroute_fraction
        n_to_reroute = max(1, int(len(zone.vehicle_ids) * frac))

        # ── 1. Filter ineligible vehicles ──────────────────────────────────
        allowed: list[str] = []
        for vid in zone.vehicle_ids:
            if self._vehicle_reroute_count.get(vid, 0) >= self.per_vehicle_reroute_cap:
                continue
            if vid.startswith("EV_"):
                continue
            try:
                vtype = traci.vehicle.getTypeID(vid).lower()
                if any(k in vtype for k in ("bus", "emergency", "ambulance", "fire", "police")):
                    continue
            except Exception:
                pass
            allowed.append(vid)

        # ── 2. Smart candidate selection — prefer vehicles with the most
        #     remaining route, then those rerouted fewest times. ──────────
        scored: list[tuple[int, int, str]] = []
        for vid in allowed:
            try:
                route     = traci.vehicle.getRoute(vid)
                idx       = traci.vehicle.getRouteIndex(vid)
                remaining = max(0, len(route) - 1 - idx)
            except Exception:
                remaining = 0
            rc = self._vehicle_reroute_count.get(vid, 0)
            scored.append((-remaining, rc, vid))
        scored.sort()

        candidates       = [t[2] for t in scored[:n_to_reroute]]
        zone_avg_before  = zone.avg_speed_cms
        rerouted         = self._rerouter.reroute(candidates)
        if not rerouted:
            return []

        # ── 3. Bookkeeping + visual tinting ────────────────────────────────
        for vid in rerouted:
            self._vehicle_reroute_count[vid] = self._vehicle_reroute_count.get(vid, 0) + 1
            try:
                self._original_colors[vid] = traci.vehicle.getColor(vid)
            except Exception:
                pass
            try:
                traci.vehicle.setColor(vid, (255, 255, 0, 200))
                self._tinted[vid] = self.color_tint_duration_ticks
            except Exception:
                pass

        zone.last_action = f"rerouted:{len(rerouted)}"
        tag = "URGENT " if urgent else ""
        print(
            f"[{self.name}] {tag}VEHICLES REROUTED | "
            f"{len(rerouted)} of {len(zone.vehicle_ids)} vehicles "
            f"({int(frac * 100)}% fraction) | ids={rerouted}"
        )

        # ── 4. Schedule effectiveness check ────────────────────────────────
        self._pending_followups.append({
            "due_step":    step + self.reroute_effectiveness_delay_ticks,
            "before_avg":  round(zone_avg_before, 1),
            "vehicle_ids": rerouted,
            "x":           zone.cx,
            "y":           zone.cy,
        })

        return [self.emit(
            type     = "vehicles_rerouted",
            msg      = (
                f"{'Urgently r' if urgent else 'R'}erouted {len(rerouted)} of "
                f"{len(zone.vehicle_ids)} congested vehicles"
            ),
            severity = "info",
            x=zone.cx, y=zone.cy,
            rerouted_count = len(rerouted),
            rerouted_ids   = rerouted,
            reason         = "hazard_zone_urgent" if urgent else "congestion_relief",
            zone_avg_speed_before = round(zone_avg_before, 1),
        )]

    # ── public API ────────────────────────────────────────────────────────────

    def force_optimize(self, data=None) -> int:
        """Force immediate optimization, bypassing the cooldown for matching zones.

        Called from the orchestrator hub when the user types e.g.
            "optimize the traffic"            → scope=all
            "fix the congestion downtown"     → scope=location, location="downtown"
        in the AI panel. The sim's _on_optimize_command callback forwards the
        payload here.

        Payload (all keys optional):
            scope     : "all" (default) | "location" | "zone"
            location  : substring matched against zone vehicle IDs / SUMO road IDs
                        of zone members (case-insensitive)
            zone_id   : integer index into the active-zone list (legacy)

        Returns the number of zones whose cooldown was reset (≥ 0).
        The actual reroute happens on the next reconcile cycle.
        """
        # Back-compat: bare int → legacy zone_id behaviour.
        if isinstance(data, int):
            data = {"scope": "zone", "zone_id": data}
        if not isinstance(data, dict):
            data = {"scope": "all"}

        scope    = (data.get("scope") or "all").lower()
        location = (data.get("location") or "").lower().strip()
        zone_id  = data.get("zone_id")

        targets: list[int] = []

        if scope == "zone" and isinstance(zone_id, int):
            if 0 <= zone_id < len(self._active_zones):
                targets = [zone_id]

        elif scope == "location" and location:
            # Match zones whose member vehicles are on a SUMO edge whose ID
            # contains the location string. Fall back to matching against
            # vehicle IDs themselves (in case route names embed locations).
            for i, z in enumerate(self._active_zones):
                hit = False
                for vid in z.vehicle_ids[:25]:    # cap the lookup
                    if location in vid.lower():
                        hit = True
                        break
                    try:
                        edge = traci.vehicle.getRoadID(vid)
                        if edge and location in edge.lower():
                            hit = True
                            break
                    except Exception:
                        continue
                if hit:
                    targets.append(i)
            # If no zone matched the hint at all, fall back to global —
            # the user asked for relief, give them something visible.
            if not targets:
                targets = list(range(len(self._active_zones)))

        else:
            # scope=all (or unrecognised)
            targets = list(range(len(self._active_zones)))

        for idx in targets:
            zone = self._active_zones[idx]
            zone.action_cooldown = 0
            print(
                f"[{self.name}] FORCE OPTIMIZE requested for zone {idx} "
                f"({len(zone.vehicle_ids)} vehicles) — scope={scope} "
                f"location={location!r}"
            )

        if not targets:
            print(f"[{self.name}] FORCE OPTIMIZE requested but no active zones.")
        return len(targets)
