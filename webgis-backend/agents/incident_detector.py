"""
agents/incident_detector.py
───────────────────────────
First concrete agent. Watches vehicle speeds and emits events
when anomalies are detected.

Emitted event types
───────────────────
  "congestion"  — vehicle slow for N consecutive ticks
  "stopped"     — vehicle stationary for N consecutive ticks
  "recovered"   — flagged vehicle back to normal speed
  "cluster"     — multiple slow vehicles near same location

Constructor arguments (all have defaults — no changes required)
───────────────────────────────────────────────────────────────
  speed_threshold_cms   : below this = "slow"  (default 500 = 5 m/s)
  slow_ticks_trigger    : ticks slow before event fires  (default 10)
  stopped_speed_cms     : below this = "stopped"  (default 50 = 0.5 m/s)
  stopped_ticks_trigger : ticks stopped before event fires  (default 25)
  cluster_radius_cm     : grouping distance for hotspot  (default 5000 cm)
  cluster_min_vehicles  : vehicles needed for cluster event  (default 3)
  emit_recovery         : emit event on speed recovery  (default True)
"""

from __future__ import annotations
from dataclasses import dataclass
from .base_agent import BaseAgent, AgentEvent


@dataclass
class _VehicleRecord:
    id:            str
    slow_ticks:    int   = 0
    stopped_ticks: int   = 0
    flagged:       bool  = False
    last_x:        float = 0.0
    last_y:        float = 0.0
    last_speed:    float = 0.0


class IncidentDetector(BaseAgent):

    def __init__(
        self,
        speed_threshold_cms:   float = 500.0,
        slow_ticks_trigger:    int   = 10,
        stopped_speed_cms:     float = 50.0,
        stopped_ticks_trigger: int   = 25,
        cluster_radius_cm:     float = 5000.0,
        cluster_min_vehicles:  int   = 3,
        emit_recovery:         bool  = True,
    ):
        super().__init__(name="IncidentDetector")
        self.speed_threshold_cms   = speed_threshold_cms
        self.slow_ticks_trigger    = slow_ticks_trigger
        self.stopped_speed_cms     = stopped_speed_cms
        self.stopped_ticks_trigger = stopped_ticks_trigger
        self.cluster_radius_cm     = cluster_radius_cm
        self.cluster_min_vehicles  = cluster_min_vehicles
        self.emit_recovery         = emit_recovery

        self._records: dict[str, _VehicleRecord] = {}
        self._cluster_cooldown: int = 0
        self._cluster_cooldown_ticks: int = 150   # ~3 s at 50 Hz

    # ── process — this is the method BaseAgent requires ──────────────────────

    def process(
        self,
        vehicles: list[dict],
        sim_time: float,
        step:     int,
        *,
        context     = None,    # AgentContext — available for future hazard awareness
        prev_events = None,    # list[AgentEvent] from previous tick
    ) -> list[AgentEvent]:

        events: list[AgentEvent] = []
        active_ids: set[str] = set()
        slow_positions: list[tuple[float, float, str]] = []

        for v in vehicles:
            vid   = str(v["id"])
            speed = float(v.get("speed", 0.0))   # cm/s
            x     = float(v.get("x", 0.0))
            y     = float(v.get("y", 0.0))
            active_ids.add(vid)

            if vid not in self._records:
                self._records[vid] = _VehicleRecord(id=vid)
            rec = self._records[vid]
            rec.last_x     = x
            rec.last_y     = y
            rec.last_speed = speed

            # stopped counter
            if speed < self.stopped_speed_cms:
                rec.stopped_ticks += 1
            else:
                rec.stopped_ticks = 0

            # slow / recovery logic
            if speed < self.speed_threshold_cms:
                rec.slow_ticks += 1
                slow_positions.append((x, y, vid))

                if rec.slow_ticks == self.slow_ticks_trigger:
                    rec.flagged = True
                    events.append(self.emit(
                        type="congestion",
                        msg=f"Vehicle {vid} slow for {rec.slow_ticks} ticks ({speed/100:.1f} m/s)",
                        vehicle=vid, severity="warning", x=x, y=y,
                        speed_cms=speed, slow_ticks=rec.slow_ticks,
                    ))

                if rec.stopped_ticks == self.stopped_ticks_trigger:
                    events.append(self.emit(
                        type="stopped",
                        msg=f"Vehicle {vid} appears stationary",
                        vehicle=vid, severity="warning", x=x, y=y,
                        stopped_ticks=rec.stopped_ticks,
                    ))
            else:
                if rec.flagged and self.emit_recovery:
                    events.append(self.emit(
                        type="recovered",
                        msg=f"Vehicle {vid} returned to normal speed ({speed/100:.1f} m/s)",
                        vehicle=vid, severity="info", x=x, y=y,
                    ))
                rec.slow_ticks = 0
                rec.flagged    = False

        # cluster detection
        if self._cluster_cooldown > 0:
            self._cluster_cooldown -= 1
        elif len(slow_positions) >= self.cluster_min_vehicles:
            cluster = self._find_cluster(slow_positions)
            if cluster and len(cluster) >= self.cluster_min_vehicles:
                cx = sum(p[0] for p in cluster) / len(cluster)
                cy = sum(p[1] for p in cluster) / len(cluster)
                self._cluster_cooldown = self._cluster_cooldown_ticks
                events.append(self.emit(
                    type="cluster",
                    msg=(f"{len(cluster)} vehicles slow within "
                         f"{self.cluster_radius_cm/100:.0f} m radius"),
                    severity="critical", x=cx, y=cy,
                    vehicle_count=len(cluster),
                    vehicle_ids=[p[2] for p in cluster],
                    radius_cm=self.cluster_radius_cm,
                ))

        # clean up departed vehicles
        for vid in set(self._records) - active_ids:
            del self._records[vid]

        return events

    # ── helpers ───────────────────────────────────────────────────────────────

    def _find_cluster(
        self,
        positions: list[tuple[float, float, str]],
    ) -> list[tuple[float, float, str]] | None:
        best: list = []
        r2 = self.cluster_radius_cm ** 2
        for i, (ax, ay, _) in enumerate(positions):
            group = [p for j, p in enumerate(positions)
                     if (ax - p[0])**2 + (ay - p[1])**2 <= r2]
            if len(group) > len(best):
                best = group
        return best if len(best) >= self.cluster_min_vehicles else None

    def flagged_vehicles(self) -> list[str]:
        return [vid for vid, rec in self._records.items() if rec.flagged]

    def on_stop(self) -> None:
        flagged = self.flagged_vehicles()
        if flagged:
            print(f"[{self.name}] {len(flagged)} still flagged at shutdown: {flagged}")
        super().on_stop()
