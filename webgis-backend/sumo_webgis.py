"""
sumo_webgis.py
──────────────
Master orchestrator for the SUMO ↔ WebGIS Angular dashboard.

Mirrors the architecture of the original sumo_simulator.py + sio_server.py:
  - Instantiates AgentManager with all agents
  - Runs SensorManager for CCTV perception
  - Broadcasts sim_metrics, agent_status, toast, qa_response, sensor_data
  - Listens for qa_query, density_command, hazard_command, optimize_command, scenario_config
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import socketio
from aiohttp import web
import traci

from agents.agent_manager import AgentManager
from agents.analytics_agent import AnalyticsAgent
from agents.incident_detector import IncidentDetector
from agents.hazard_agent import HazardAgent
from agents.adaptive_spawning_agent import AdaptiveSpawningAgent
from agents.traffic_optimizer import TrafficOptimizationAgent
from sensor_manager import SensorManager
from qa_handler import get_qa_handler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sumo_webgis")

SUMO_CONFIG_PATH = r"c:\SCDT\webgis-backend\linz.sumocfg"


class WebGISSumoServer:
    def __init__(self, host="127.0.0.1", port=3000):
        self.host = host
        self.port = port
        self.sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins="*")
        self.app = web.Application()
        self.sio.attach(self.app)

        # Shared state for cross-thread command passing
        self._pending_scenario: dict | None = None
        self._agent_manager: AgentManager | None = None
        self._sensor_manager: SensorManager | None = None

        self._setup_sio_events()

    # ── Socket.IO Event Listeners ─────────────────────────────────────────────

    def _setup_sio_events(self):
        sio = self.sio

        @sio.event
        async def connect(sid, environ):
            log.info("Client connected: %s", sid)

        @sio.event
        async def disconnect(sid):
            log.info("Client disconnected: %s", sid)

        @sio.on("qa_query")
        async def on_qa_query(sid, data):
            query = data.get("query", "") if isinstance(data, dict) else str(data)
            log.info("QA query from %s: %s", sid, query)
            handler = get_qa_handler()
            result = handler.process_query(query)
            await sio.emit("qa_response", {
                "query": query,
                "answer": result.get("answer", ""),
                "confidence": result.get("confidence", 0.0),
                "source": result.get("source", ""),
            }, room=sid)

        @sio.on("density_command")
        async def on_density_command(sid, data):
            log.info("Density command from %s: %s", sid, data)
            if self._agent_manager is None:
                await sio.emit("toast", {
                    "type": "warning",
                    "title": "Not Ready",
                    "message": "Simulation not yet started.",
                }, room=sid)
                return

            agent = self._agent_manager.get("AdaptiveSpawningAgent")
            if agent and hasattr(agent, "set_density_target"):
                result = agent.set_density_target(
                    min_vehicles=data.get("min_vehicles"),
                    max_vehicles=data.get("max_vehicles"),
                )
                await sio.emit("density_applied", {
                    "success": True,
                    "message": f"Density target updated: {result['new_min']}–{result['new_max']}",
                    **result,
                })
                await sio.emit("toast", {
                    "type": "success",
                    "title": "Density Updated",
                    "message": f"Target: {result['new_min']}–{result['new_max']} vehicles",
                })

        @sio.on("hazard_command")
        async def on_hazard_command(sid, data):
            log.info("Hazard command from %s: %s", sid, data)
            await sio.emit("hazard_applied", {
                "success": True,
                "message": "Hazard command received.",
            }, room=sid)

        @sio.on("optimize_command")
        async def on_optimize_command(sid, data):
            log.info("Optimize command from %s: %s", sid, data)
            if self._agent_manager is None:
                return

            agent = self._agent_manager.get("TrafficOptimizationAgent")
            if agent and hasattr(agent, "force_optimize"):
                result = agent.force_optimize(data=data)
                await sio.emit("toast", {
                    "type": "info",
                    "title": "Optimization Triggered",
                    "message": f"Rerouting scope: {data.get('scope', 'all')}",
                })

        @sio.on("scenario_config")
        async def on_scenario_config(sid, data):
            log.info("Scenario config from %s: %s", sid, data)
            self._pending_scenario = data
            await sio.emit("scenario_applied", {
                "success": True,
                "message": "Scenario config queued.",
            }, room=sid)

    # ── Simulation Loop ───────────────────────────────────────────────────────

    async def _simulation_loop(self):
        log.info("Starting SUMO simulation...")

        try:
            sumo_dir = Path(SUMO_CONFIG_PATH).parent
            os.chdir(sumo_dir)

            traci.start(["sumo", "-c", SUMO_CONFIG_PATH, "--step-length", "0.1"])

            # ── Instantiate all agents ────────────────────────────────────
            agent_manager = AgentManager()
            agent_manager.register(IncidentDetector())
            agent_manager.register(HazardAgent())
            agent_manager.register(AdaptiveSpawningAgent(
                min_vehicles=10,
                max_vehicles=50,
                check_interval=50,
            ))
            agent_manager.register(AnalyticsAgent(report_interval_ticks=50))
            agent_manager.register(TrafficOptimizationAgent())
            agent_manager.start()
            self._agent_manager = agent_manager

            # ── Instantiate sensor manager ────────────────────────────────
            sensor_mgr = SensorManager(config_path="config/sensor_layout.json")
            self._sensor_manager = sensor_mgr
            log.info("Loaded %d sensors", len(sensor_mgr.sensors))

            step_count = 0
            sim_start_wall = time.monotonic()

            # Metrics accumulators
            total_distance_cm = 0.0
            prev_positions: dict[str, tuple[float, float]] = {}
            metrics_history: list[dict] = []

            while traci.simulation.getMinExpectedNumber() > 0:
                traci.simulationStep()
                step_count += 1

                vehicle_ids = traci.vehicle.getIDList()
                sim_time = traci.simulation.getTime()

                # ── Check for pending scenario config ─────────────────────
                if self._pending_scenario:
                    cfg = self._pending_scenario
                    self._pending_scenario = None
                    self._apply_scenario(cfg, vehicle_ids)

                # ── Collect vehicles ──────────────────────────────────────
                payload_batch = []
                agent_vehicles = []

                for vid in vehicle_ids:
                    x, y = traci.vehicle.getPosition(vid)
                    lon, lat = traci.simulation.convertGeo(x, y)
                    speed = traci.vehicle.getSpeed(vid)

                    v_payload = {
                        "id": vid,
                        "lon": lon,
                        "lat": lat,
                        "z": 0.0,
                        "speed": speed,
                    }
                    payload_batch.append(v_payload)

                    x_cm = x * 100
                    y_cm = y * 100
                    speed_cms = speed * 100

                    # Distance tracking
                    if vid in prev_positions:
                        px, py = prev_positions[vid]
                        dx = x_cm - px
                        dy = y_cm - py
                        total_distance_cm += (dx * dx + dy * dy) ** 0.5
                    prev_positions[vid] = (x_cm, y_cm)

                    agent_vehicles.append({
                        "id": vid,
                        "x": x_cm,
                        "y": y_cm,
                        "z": 0.0,
                        "yaw_deg": traci.vehicle.getAngle(vid),
                        "speed": speed_cms,
                    })

                # ── Emit vehicle telemetry (per-vehicle) ─────────────────
                for vp in payload_batch:
                    await self.sio.emit("message", vp)

                # ── Run sensor manager (every ~3 ticks ≈ 15 Hz at 50 Hz) ─
                sensor_data: dict = {}
                if step_count % 3 == 0 and agent_vehicles:
                    sensor_data = sensor_mgr.tick(agent_vehicles, sim_time, step_count)

                # ── Run all agents ────────────────────────────────────────
                events = agent_manager.tick(
                    agent_vehicles, sim_time, step_count, sensor_data
                )

                # ── Process agent events → broadcast ──────────────────────
                for ev in events:
                    ev_dict = ev.to_dict()

                    if ev.type == "analytics_snapshot":
                        await self.sio.emit("sim_metrics", ev_dict)
                    elif ev.type in ("business_analytics", "zone_analytics"):
                        await self.sio.emit("sim_metrics", ev_dict)
                    elif ev.type == "density_updated":
                        await self.sio.emit("toast", {
                            "type": "info",
                            "title": "Density Updated",
                            "message": ev.msg,
                        })
                    elif ev.type == "hazard_alert":
                        await self.sio.emit("toast", {
                            "type": "critical",
                            "title": "Hazard Alert",
                            "message": ev.msg,
                        })
                    elif ev.type in ("congestion_detected", "cluster"):
                        await self.sio.emit("toast", {
                            "type": "warning",
                            "title": "Congestion",
                            "message": ev.msg,
                        })

                # ── Emit sim_metrics summary (every 50 ticks ≈ 5s) ───────
                if step_count % 50 == 0:
                    n = len(agent_vehicles)
                    avg_speed_cms = 0.0
                    if n > 0:
                        avg_speed_cms = sum(v["speed"] for v in agent_vehicles) / n

                    metrics_payload = {
                        "type": "sim_summary",
                        "sim_time": round(sim_time, 2),
                        "step": step_count,
                        "total_vehicles": n,
                        "avg_speed_cms": round(avg_speed_cms, 1),
                        "avg_speed_kmh": round(avg_speed_cms * 0.036, 1),
                        "total_distance_km": round(total_distance_cm / 100000, 2),
                    }
                    await self.sio.emit("sim_metrics", metrics_payload)
                    metrics_history.append(metrics_payload)

                # ── Emit agent_status (every 100 ticks ≈ 10s) ────────────
                if step_count % 100 == 0:
                    agents_status = []
                    for ag in agent_manager.agents:
                        density_pct = None
                        if ag.name == "AdaptiveSpawningAgent":
                            n = len(agent_vehicles)
                            max_v = ag.max_vehicles if ag.max_vehicles > 0 else 1
                            density_pct = round(min(100.0, (n / max_v) * 100), 1)

                        agents_status.append({
                            "name": ag.name,
                            "enabled": ag.enabled,
                            "event_count": ag.event_count,
                            "tick_count": ag.tick_count,
                            "status": "active" if ag.enabled else "disabled",
                            "density_pct": density_pct,
                        })
                    await self.sio.emit("agent_status", {"agents": agents_status})

                # ── Emit sensor_data (every 50 ticks) ────────────────────
                if step_count % 50 == 0 and sensor_data:
                    sensor_status = sensor_mgr.get_sensor_status(sensor_data)
                    sensor_counts = {}
                    for sid, vlist in sensor_data.items():
                        sensor_counts[sid] = len(vlist)
                    await self.sio.emit("sensor_data", {
                        "sensors": sensor_status,
                        "counts": sensor_counts,
                    })

                # ── Logging ───────────────────────────────────────────────
                if int(sim_time * 10) % 50 == 0:
                    log.info(
                        "t=%.1fs vehicles=%d events=%d",
                        sim_time, len(vehicle_ids), len(events),
                    )

                await asyncio.sleep(0.1)

        except Exception as e:
            log.error("Simulation error: %s", e, exc_info=True)
        finally:
            if self._agent_manager:
                self._agent_manager.stop()
            try:
                traci.close()
            except Exception:
                pass
            log.info("SUMO simulation ended.")

    # ── Scenario helpers ──────────────────────────────────────────────────────

    def _apply_scenario(self, cfg: dict, vehicle_ids):
        if "vehicle_count" in cfg:
            target = int(cfg["vehicle_count"])
            current = len(vehicle_ids)
            if self._agent_manager:
                agent = self._agent_manager.get("AdaptiveSpawningAgent")
                if agent and hasattr(agent, "set_density_target"):
                    agent.set_density_target(
                        min_vehicles=max(1, target - 5),
                        max_vehicles=target + 5,
                    )
            log.info("Scenario: vehicle_count target=%d (current=%d)", target, current)

        if "speed_limit" in cfg:
            limit_kmh = float(cfg["speed_limit"])
            limit_ms = limit_kmh / 3.6
            for eid in traci.edge.getIDList():
                try:
                    traci.edge.setMaxSpeed(eid, limit_ms)
                except Exception:
                    pass
            log.info("Scenario: speed_limit=%.0f km/h", limit_kmh)

    # ── Server entry point ────────────────────────────────────────────────────

    async def run(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        log.info("WebGIS Socket.IO server running on http://%s:%d", self.host, self.port)

        asyncio.create_task(self._simulation_loop())

        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    if not Path(SUMO_CONFIG_PATH).exists():
        log.error("SUMO config not found at: %s", SUMO_CONFIG_PATH)
        sys.exit(1)

    server = WebGISSumoServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        log.info("Shutting down...")
