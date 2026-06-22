"""
agents/base_agent.py
────────────────────
Base class for all agents in the SUMO → Unreal Engine bridge.

Every agent receives the vehicle list once per simulation tick and
optionally returns AgentEvent objects that get added to the UDP packet.

To create a new agent:
    1. Subclass BaseAgent
    2. Override process(vehicles, sim_time, step) → list[AgentEvent]
    3. Register it in your AgentManager instance
"""

from __future__ import annotations
from dataclasses import dataclass, field
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import AgentContext


# ── AgentEvent ────────────────────────────────────────────────────────────────

@dataclass
class AgentEvent:
    """
    A structured event emitted by an agent.

    Gets broadcast over UDP in the "events" key alongside vehicles:

        {
          "t": 142.34, "step": 7117, "units": "cm",
          "vehicles": [...],
          "events": [
            {
              "agent": "IncidentDetector",
              "type": "congestion",
              "vehicle": "42",
              "severity": "warning",
              "msg": "Vehicle 42 slow for 10 ticks (3.2 m/s)",
              "x": 15850.0,
              "y": 27010.0
            }
          ]
        }

    Unreal Blueprint can switch on "type" to trigger alerts or camera cuts.
    """

    agent:    str
    type:     str
    msg:      str   = ""
    vehicle:  str   = ""
    severity: str   = "info"   # "info" | "warning" | "critical"
    source_sensor: str = ""
    confidence: float = 1.0
    x:        float = 0.0
    y:        float = 0.0
    data:     dict  = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "agent":    self.agent,
            "type":     self.type,
            "msg":      self.msg,
            "severity": self.severity,
        }
        if self.vehicle:
            d["vehicle"] = self.vehicle
        if self.x or self.y:
            d["x"] = self.x
            d["y"] = self.y
        if self.source_sensor:
            d["source_sensor"] = self.source_sensor
        if self.confidence != 1.0:
            d["confidence"] = self.confidence
        if self.data:
            d.update(self.data)
        return d


# ── BaseAgent ─────────────────────────────────────────────────────────────────

class BaseAgent:
    """
    Abstract base class. Subclasses must implement process().

    DO NOT add on_tick() — the method is process().
    """

    def __init__(self, name: str | None = None):
        self.name:        str  = name or self.__class__.__name__
        self.enabled:     bool = True
        self.tick_count:  int  = 0
        self.event_count: int  = 0
        self._start_time: float = 0.0
        self.sensor_data: dict = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        """Called once before the simulation loop starts."""
        self._start_time = time.monotonic()

    def on_stop(self) -> None:
        """Called once after the simulation loop ends."""
        elapsed = time.monotonic() - self._start_time
        print(
            f"[{self.name}] stopped — "
            f"{self.tick_count} ticks, "
            f"{self.event_count} events, "
            f"{elapsed:.1f}s"
        )

    # ── MAIN HOOK — override this in every subclass ───────────────────────────

    def process(
        self,
        vehicles:    list[dict],
        sim_time:    float,
        step:        int,
        *,
        context     = None,    # AgentContext — None for solo runs / tests
        prev_events = None,    # list[AgentEvent] from the previous tick
    ) -> list[AgentEvent]:
        """
        Called every simulation tick with the current vehicle list.

        Parameters
        ----------
        vehicles : list[dict]
            Keys: id, x, y, z, yaw_deg, speed
            Positions in Unreal cm. Speed in cm/s.
        sim_time : float
            Current simulation time in seconds.
        step : int
            Current step counter.
        context : AgentContext | None
            Shared state for cross-agent coordination. Agents may write
            their published snapshots here, and read other agents' state
            (e.g. active hazards / congestion zones).
        prev_events : list[AgentEvent] | None
            Every AgentEvent emitted by ALL agents on the previous tick.
            Use for reactive coordination.

        Returns
        -------
        list[AgentEvent]
            Events to broadcast. Return [] if nothing to report.
        """
        raise NotImplementedError(f"{self.name}.process() must be implemented")

    # ── internal wrapper called by AgentManager ───────────────────────────────

    def _tick(
        self,
        vehicles:    list[dict],
        sim_time:    float,
        step:        int,
        *,
        context     = None,
        prev_events = None,
    ) -> list[AgentEvent]:
        if not self.enabled:
            return []
        self.tick_count += 1
        try:
            events = self.process(
                vehicles, sim_time, step,
                context=context, prev_events=prev_events,
            )
        except Exception as exc:
            print(f"[{self.name}] ERROR in process(): {exc}")
            return []
        self.event_count += len(events)
        return events

    # ── convenience factory ───────────────────────────────────────────────────

    def emit(
        self,
        type:     str,
        msg:      str   = "",
        vehicle:  str   = "",
        severity: str   = "info",
        x:        float = 0.0,
        y:        float = 0.0,
        **kwargs,
    ) -> AgentEvent:
        """Create an AgentEvent with self.name pre-filled."""
        return AgentEvent(
            agent=self.name,
            type=type,
            msg=msg,
            vehicle=vehicle,
            severity=severity,
            x=x,
            y=y,
            data=kwargs,
        )

    def __repr__(self) -> str:
        status = "ON" if self.enabled else "OFF"
        return f"<{self.name} [{status}] ticks={self.tick_count}>"
