"""
agents/agent_manager.py
───────────────────────
Orchestrates all registered agents and drives their tick cycle.

Integration in sumo_simulator.py (3 steps):
────────────────────────────────────────────
    # 1. Import at top of sumo_simulator.py
    from agents.agent_manager import AgentManager
    from agents.incident_detector import IncidentDetector

    # 2. In SUMOSimulator.__init__():
    self.agent_manager = AgentManager()
    self.agent_manager.register(IncidentDetector())

    # 3. In the simulation loop, after building vehicle_list:
    events = self.agent_manager.tick(vehicle_list, sim_time, step)
    self.streamer.send_vehicles(vehicle_list, events=events)

    # 4. After the loop:
    self.agent_manager.start()   # before loop
    self.agent_manager.stop()    # after loop
"""

from __future__ import annotations
from .base_agent import BaseAgent, AgentEvent
from .context   import AgentContext


class AgentManager:

    def __init__(self):
        self.agents:       list[BaseAgent] = []
        self.total_ticks:  int = 0
        self.total_events: int = 0

        # Shared state every agent can read/write each tick. Carries active
        # hazards (from HazardAgent), congestion zones (from
        # TrafficOptimizationAgent), and the current sim clock.
        self.context: AgentContext = AgentContext()

        # Last tick's emitted events, passed to every agent on the next tick.
        # This is the "feedback loop" — an agent can react to a peer's action
        # without being coupled to it.
        self._prev_events: list[AgentEvent] = []

    # ── registration ─────────────────────────────────────────────────────────

    def register(self, agent: BaseAgent) -> "AgentManager":
        """Add an agent. Returns self for chaining."""
        if not isinstance(agent, BaseAgent):
            raise TypeError(f"Expected BaseAgent subclass, got {type(agent)}")
        self.agents.append(agent)
        print(f"[AgentManager] registered: {agent.name}")
        return self

    def get(self, name: str) -> BaseAgent | None:
        return next((a for a in self.agents if a.name == name), None)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        for agent in self.agents:
            try:
                agent.on_start()
            except Exception as exc:
                print(f"[AgentManager] {agent.name}.on_start() error: {exc}")
        print(f"[AgentManager] started {len(self.agents)} agent(s): "
              f"{[a.name for a in self.agents]}")

    def stop(self) -> None:
        for agent in self.agents:
            try:
                agent.on_stop()
            except Exception as exc:
                print(f"[AgentManager] {agent.name}.on_stop() error: {exc}")
        print(f"[AgentManager] stopped — "
              f"{self.total_ticks} ticks, {self.total_events} events")

    # ── tick ──────────────────────────────────────────────────────────────────

    def tick(
        self,
        vehicles:    list[dict],
        sim_time:    float,
        step:        int,
        sensor_data: dict | None = None,
    ) -> list[AgentEvent]:
        """
        Run all agents for one simulation step.
        Call once per SUMO step, after building vehicle_list.

        Threads the shared `AgentContext` and the previous tick's events
        through to every agent, enabling cross-agent coordination.
        Also injects `sensor_data` into `agent.sensor_data` for CCTV-aware agents.
        """
        # Refresh shared clock so spatial/temporal queries are consistent.
        self.context.sim_time = sim_time
        self.context.step     = step

        prev_events = self._prev_events
        all_events: list[AgentEvent] = []
        _sensor_data = sensor_data or {}

        for agent in self.agents:
            # Expose CCTV sensor data via agent attribute (backward-compatible)
            agent.sensor_data = _sensor_data
            all_events.extend(agent._tick(
                vehicles, sim_time, step,
                context=self.context, prev_events=prev_events,
            ))

        # Save for next tick's prev_events.
        self._prev_events = all_events

        self.total_ticks  += 1
        self.total_events += len(all_events)
        return all_events

    def __len__(self)  -> int:  return len(self.agents)
    def __repr__(self) -> str:
        return (f"<AgentManager agents={len(self.agents)} "
                f"ticks={self.total_ticks} events={self.total_events}>")
