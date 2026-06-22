"""
agents/analytics_agent.py
─────────────────────────
Analytics Agent — comprehensive metrics collection and reporting.

Tracks:
  • Global metrics (average speed, density, vehicle count)
  • Zone-based metrics (congestion hotspots, regional analytics)
  • Per-vehicle metrics (speeds, acceleration, traveled distance)
  • Agent performance (events fired per agent, incident counts)
  • Route efficiency (active routes, vehicle distribution)
  • Incident tracking (cumulative incidents by type)

Emitted event types
───────────────────
  "analytics_snapshot"  — periodic comprehensive analytics report
  "zone_analytics"      — detailed analytics for detected congestion zones

Constructor arguments (all have defaults)
─────────────────────────────────────────
  report_interval_ticks  : ticks between analytics events (default 500 = ~10s @ 50Hz)
  zone_radius_cm         : grouping distance for zone detection (default 8000)
  zone_min_vehicles      : min vehicles to form a zone (default 3)
"""

from __future__ import annotations
import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from .base_agent import BaseAgent, AgentEvent
try:
    from analytics_store import set_latest  # when run from Sumo_Aligned_Scripts/
except ImportError:
    from ..analytics_store import set_latest  # fallback for package installs

log_enabled = False  # Set to True for debug output


def _log(msg: str):
    if log_enabled:
        print(f"[AnalyticsAgent] {msg}")


@dataclass
class _VehicleSnapshot:
    """Capture of a vehicle's state for cumulative tracking."""
    id: str
    x: float
    y: float
    speed_cms: float
    prev_x: float = 0.0
    prev_y: float = 0.0
    prev_speed_cms: float = 0.0
    total_distance_cm: float = 0.0
    max_speed_cms: float = 0.0
    min_speed_cms: float = float("inf")
    tick_count: int = 0


@dataclass
class _ZoneMetrics:
    """Metrics for a detected zone."""
    zone_id: str
    cx: float
    cy: float
    vehicle_ids: list[str] = field(default_factory=list)
    avg_speed_cms: float = 0.0
    vehicle_count: int = 0
    density_vehicles_per_sqkm: float = 0.0
    is_congested: bool = False


@dataclass
class _GlobalMetrics:
    """Snapshot of global simulation metrics."""
    timestamp: float
    total_vehicles: int
    avg_speed_cms: float
    max_speed_cms: float
    min_speed_cms: float
    total_distance_cm: float
    active_zones: int
    congested_zones: int
    incidents_this_interval: int


@dataclass
class _BusinessAnalytics:
    """Business-focused metrics for decision-making."""
    # Operational Efficiency
    throughput_veh_per_min: float = 0.0
    avg_travel_delay_sec: float = 0.0
    congestion_cost_index: float = 0.0
    network_utilization_pct: float = 0.0
    
    # Safety & Risk
    incident_rate_per_100veh_km: float = 0.0
    avg_incident_severity: float = 0.0
    high_risk_zone_count: int = 0
    speed_violation_pct: float = 0.0
    
    # Economic Impact
    estimated_fuel_consumption_l: float = 0.0
    estimated_co2_emissions_kg: float = 0.0
    time_lost_to_congestion_veh_hrs: float = 0.0
    congestion_economic_cost_usd: float = 0.0
    
    # Demand & Capacity
    peak_hour_detected: bool = False
    utilization_ratio: float = 0.0
    bottleneck_severity_score: float = 0.0
    vehicle_distribution_balance: float = 0.0
    
    # Vehicle Performance
    avg_acceleration_cms2: float = 0.0
    harsh_acceleration_events: int = 0
    speed_limit_compliance_pct: float = 100.0
    tire_wear_index: float = 0.0
    
    # Predictive Insights
    congestion_trend: str = "stable"  # "increasing", "decreasing", "stable"
    incident_trend: str = "stable"
    anomaly_detected: bool = False
    anomaly_type: str = ""


class AnalyticsAgent(BaseAgent):
    """
    Comprehensive analytics collector and reporter.
    Emits periodic snapshots of simulation state to Unreal via UDP.
    """

    def __init__(
        self,
        report_interval_ticks: int = 500,
        zone_radius_cm: float = 8000.0,
        zone_min_vehicles: int = 3,
    ):
        super().__init__(name="AnalyticsAgent")
        self.report_interval_ticks = report_interval_ticks
        self.zone_radius_cm = zone_radius_cm
        self.zone_min_vehicles = zone_min_vehicles

        # ── cumulative state ──────────────────────────────────────────
        self._vehicle_snapshots: dict[str, _VehicleSnapshot] = {}
        self._total_ticks_monitored: int = 0
        self._incident_count_by_type: dict[str, int] = {}
        self._events_per_agent: dict[str, int] = {}

        # ── interval tracking ──────────────────────────────────────────
        self._ticks_since_report: int = 0
        self._incidents_this_interval: int = 0
        
        # ── business analytics tracking ───────────────────────────────
        self._vehicle_count_history: list[int] = []
        self._avg_speed_history: list[float] = []
        self._congestion_zone_history: list[int] = []
        self._incident_history: list[int] = []
        self._vehicles_exited_this_interval: int = 0
        self._speed_violations: dict[str, int] = {}
        self._harsh_acceleration_events: dict[str, int] = {}

        # Groq / free Grok LLM integration
        self.grok_api_key = os.getenv("GROQ_API_KEY") or os.getenv("FREE_GROK_API_KEY")
        self.grok_api_url = os.getenv(
            "GROQ_API_URL",
            "https://api.groq.com/v1/chat/completions",
        )
        self.grok_model = os.getenv("GROQ_MODEL", "groq2-small")
        self.grok_timeout = int(os.getenv("GROQ_TIMEOUT_SECONDS", "10"))

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        super().on_start()
        print(
            f"[{self.name}] started — "
            f"reporting every {self.report_interval_ticks} ticks, "
            f"zone radius={self.zone_radius_cm}cm, min_vehicles={self.zone_min_vehicles}"
        )

    def on_stop(self) -> None:
        print(
            f"[{self.name}] summary — "
            f"monitored {self._total_ticks_monitored} ticks, "
            f"incident types: {self._incident_count_by_type}"
        )
        super().on_stop()

    # ── main hook ─────────────────────────────────────────────────────────────

    def process(
        self,
        vehicles:    list[dict],
        sim_time:    float,
        step:        int,
        *,
        context     = None,    # AgentContext — accepted but unused here
        prev_events = None,    # list[AgentEvent] from previous tick — unused here
    ) -> list[AgentEvent]:
        """
        Collect analytics each tick, emit reports at interval.
        """
        events: list[AgentEvent] = []

        # Update vehicle snapshots
        self._update_vehicle_snapshots(vehicles)
        self._total_ticks_monitored += 1
        self._ticks_since_report += 1

        # Check if time to report
        if self._ticks_since_report >= self.report_interval_ticks:
            report_events = self._generate_report(vehicles, sim_time, step)
            events.extend(report_events)
            self._ticks_since_report = 0
            self._incidents_this_interval = 0

        return events

    # ── internal: vehicle tracking ────────────────────────────────────────────

    def _update_vehicle_snapshots(self, vehicles: list[dict]) -> None:
        """Update cumulative per-vehicle metrics."""
        active_ids = set()
        MAX_SPEED_CMS = 5000  # 50 m/s = 180 km/h speed limit

        for v in vehicles:
            vid = str(v["id"])
            active_ids.add(vid)
            x = float(v.get("x", 0.0))
            y = float(v.get("y", 0.0))
            speed = float(v.get("speed", 0.0))

            if vid not in self._vehicle_snapshots:
                self._vehicle_snapshots[vid] = _VehicleSnapshot(
                    id=vid, x=x, y=y, speed_cms=speed, max_speed_cms=speed
                )
            else:
                snap = self._vehicle_snapshots[vid]
                snap.prev_x = snap.x
                snap.prev_y = snap.y
                snap.prev_speed_cms = snap.speed_cms
                snap.x = x
                snap.y = y
                snap.speed_cms = speed
                snap.max_speed_cms = max(snap.max_speed_cms, speed)
                snap.min_speed_cms = min(snap.min_speed_cms, speed)

                # Calculate distance traveled
                dx = x - snap.prev_x
                dy = y - snap.prev_y
                dist = math.sqrt(dx * dx + dy * dy)
                snap.total_distance_cm += dist
                
                # Track acceleration (change in speed)
                accel_cms2 = speed - snap.prev_speed_cms
                if abs(accel_cms2) > 500:  # Harsh acceleration > 5 m/s²
                    self._harsh_acceleration_events[vid] = (
                        self._harsh_acceleration_events.get(vid, 0) + 1
                    )
                
                # Track speed violations
                if speed > MAX_SPEED_CMS:
                    self._speed_violations[vid] = (
                        self._speed_violations.get(vid, 0) + 1
                    )

            self._vehicle_snapshots[vid].tick_count += 1

        # Clean up departed vehicles
        departed = set(self._vehicle_snapshots) - active_ids
        self._vehicles_exited_this_interval = len(departed)
        for vid in departed:
            del self._vehicle_snapshots[vid]

    # ── internal: zone detection ──────────────────────────────────────────────

    def _detect_zones(self, vehicles: list[dict]) -> list[_ZoneMetrics]:
        """
        Cluster vehicles into zones based on spatial proximity.
        Returns zones with at least zone_min_vehicles vehicles.
        """
        if len(vehicles) < self.zone_min_vehicles:
            return []

        zones: list[_ZoneMetrics] = []
        assigned = set()
        r2 = self.zone_radius_cm ** 2

        for i, v1 in enumerate(vehicles):
            if i in assigned:
                continue

            vid1 = str(v1["id"])
            x1 = float(v1.get("x", 0.0))
            y1 = float(v1.get("y", 0.0))
            speed1 = float(v1.get("speed", 0.0))

            # Find all neighbors within radius
            zone_vehicles = [v1]
            zone_ids = [vid1]
            assigned.add(i)

            for j, v2 in enumerate(vehicles):
                if j in assigned:
                    continue
                x2 = float(v2.get("x", 0.0))
                y2 = float(v2.get("y", 0.0))
                dist_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
                if dist_sq <= r2:
                    zone_vehicles.append(v2)
                    zone_ids.append(str(v2["id"]))
                    assigned.add(j)

            # Only keep if meets minimum threshold
            if len(zone_vehicles) >= self.zone_min_vehicles:
                cx = sum(float(v.get("x", 0.0)) for v in zone_vehicles) / len(
                    zone_vehicles
                )
                cy = sum(float(v.get("y", 0.0)) for v in zone_vehicles) / len(
                    zone_vehicles
                )
                avg_speed = sum(float(v.get("speed", 0.0)) for v in zone_vehicles) / len(
                    zone_vehicles
                )

                # Approximate density (vehicles per sq km)
                # Zone area: pi * r^2, convert cm^2 to km^2
                area_km2 = (math.pi * (self.zone_radius_cm / 100000.0) ** 2)
                density = len(zone_vehicles) / area_km2 if area_km2 > 0 else 0

                zone = _ZoneMetrics(
                    zone_id=f"Z_{len(zones)}",
                    cx=cx,
                    cy=cy,
                    vehicle_ids=zone_ids,
                    avg_speed_cms=avg_speed,
                    vehicle_count=len(zone_vehicles),
                    density_vehicles_per_sqkm=density,
                    is_congested=avg_speed < 500,  # < 5 m/s
                )
                zones.append(zone)

        return zones

    # ── internal: business analytics calculation ──────────────────────────────

    def _calculate_business_analytics(
        self,
        vehicles: list[dict],
        zones: list[_ZoneMetrics],
        global_metrics: _GlobalMetrics,
    ) -> _BusinessAnalytics:
        """Calculate comprehensive business-focused metrics."""
        metrics = _BusinessAnalytics()

        # ─ Operational Efficiency ─────────────────────────────────────────
        metrics.throughput_veh_per_min = (
            self._vehicles_exited_this_interval * 60 / (self.report_interval_ticks / 50)
            if self.report_interval_ticks > 0
            else 0
        )
        metrics.avg_travel_delay_sec = max(
            0, (50 - global_metrics.avg_speed_cms / 100) / 10
        )
        metrics.congestion_cost_index = (
            global_metrics.congested_zones / max(1, global_metrics.active_zones)
            if global_metrics.active_zones > 0
            else 0
        )
        metrics.network_utilization_pct = min(100.0, (len(vehicles) / 500) * 100)

        # ─ Safety & Risk ──────────────────────────────────────────────────
        total_distance_km = (
            global_metrics.total_distance_cm / 100000
            if global_metrics.total_distance_cm > 0
            else 1
        )
        metrics.incident_rate_per_100veh_km = (
            (self._incidents_this_interval * 100) / total_distance_km
            if total_distance_km > 0
            else 0
        )
        metrics.avg_incident_severity = (
            sum(self._incident_count_by_type.values()) / len(self._incident_count_by_type)
            if self._incident_count_by_type
            else 0
        )
        metrics.high_risk_zone_count = sum(
            1 for z in zones if z.is_congested and z.vehicle_count > 5
        )
        total_violations = sum(self._speed_violations.values())
        metrics.speed_violation_pct = (
            (total_violations / (len(self._vehicle_snapshots) * self.report_interval_ticks))
            * 100
            if len(self._vehicle_snapshots) > 0
            else 0
        )

        # ─ Economic Impact ────────────────────────────────────────────────
        # Fuel consumption estimate (L/km): 0.08 L/km per vehicle
        metrics.estimated_fuel_consumption_l = total_distance_km * 0.08
        # CO2 emissions (kg/L): 2.31 kg CO2 per liter
        metrics.estimated_co2_emissions_kg = metrics.estimated_fuel_consumption_l * 2.31
        # Time lost to congestion: vehicles * delay_hours
        total_vehicle_hours = (
            sum(s.tick_count for s in self._vehicle_snapshots.values()) / 50 / 3600
        )
        metrics.time_lost_to_congestion_veh_hrs = (
            total_vehicle_hours * (metrics.avg_travel_delay_sec / 3600)
        )
        # Congestion cost: $0.50 per vehicle-hour lost
        metrics.congestion_economic_cost_usd = (
            metrics.time_lost_to_congestion_veh_hrs * 0.50
        )

        # ─ Demand & Capacity ──────────────────────────────────────────────
        avg_hist_vehicles = (
            sum(self._vehicle_count_history[-10:]) / len(self._vehicle_count_history[-10:])
            if self._vehicle_count_history
            else 0
        )
        metrics.peak_hour_detected = len(vehicles) > avg_hist_vehicles * 1.2
        metrics.utilization_ratio = len(vehicles) / 500  # Assuming max capacity 500
        metrics.bottleneck_severity_score = (
            (metrics.high_risk_zone_count * metrics.congestion_cost_index) / 10
        )
        # Vehicle distribution balance (1.0 = perfectly balanced)
        if zones:
            zone_sizes = [z.vehicle_count for z in zones]
            avg_zone_size = sum(zone_sizes) / len(zone_sizes)
            variance = sum((s - avg_zone_size) ** 2 for s in zone_sizes) / len(zone_sizes)
            std_dev = math.sqrt(variance)
            metrics.vehicle_distribution_balance = (
                1.0 - min(1.0, std_dev / max(avg_zone_size, 1.0))
            )
        else:
            metrics.vehicle_distribution_balance = 1.0

        # ─ Vehicle Performance ────────────────────────────────────────────
        total_acceleration = 0
        total_accel_count = 0
        for snap in self._vehicle_snapshots.values():
            if snap.tick_count > 1:
                accel = (snap.speed_cms - snap.prev_speed_cms) / max(1, snap.tick_count)
                total_acceleration += abs(accel)
                total_accel_count += 1
        metrics.avg_acceleration_cms2 = (
            total_acceleration / total_accel_count if total_accel_count > 0 else 0
        )
        metrics.harsh_acceleration_events = sum(
            self._harsh_acceleration_events.values()
        )
        metrics.speed_limit_compliance_pct = (
            100.0
            - metrics.speed_violation_pct
            if metrics.speed_violation_pct <= 100
            else 0.0
        )
        # Tire wear index (based on acceleration intensity and distance)
        metrics.tire_wear_index = (
            (metrics.harsh_acceleration_events + total_distance_km * 0.01) / 100
        )

        # ─ Predictive Insights ────────────────────────────────────────────
        # Congestion trend analysis
        if len(self._congestion_zone_history) >= 2:
            recent_congestion = sum(self._congestion_zone_history[-3:]) / 3
            older_congestion = (
                sum(self._congestion_zone_history[-6:-3]) / 3
                if len(self._congestion_zone_history) >= 6
                else recent_congestion
            )
            if recent_congestion > older_congestion * 1.1:
                metrics.congestion_trend = "increasing"
            elif recent_congestion < older_congestion * 0.9:
                metrics.congestion_trend = "decreasing"
            else:
                metrics.congestion_trend = "stable"

        # Incident trend analysis
        if len(self._incident_history) >= 2:
            recent_incidents = sum(self._incident_history[-3:]) / 3
            older_incidents = (
                sum(self._incident_history[-6:-3]) / 3
                if len(self._incident_history) >= 6
                else recent_incidents
            )
            if recent_incidents > older_incidents * 1.1:
                metrics.incident_trend = "increasing"
            elif recent_incidents < older_incidents * 0.9:
                metrics.incident_trend = "decreasing"
            else:
                metrics.incident_trend = "stable"

        # Anomaly detection
        if len(self._vehicle_count_history) >= 3:
            avg_count = sum(self._vehicle_count_history[-3:]) / 3
            if len(vehicles) > avg_count * 1.5:
                metrics.anomaly_detected = True
                metrics.anomaly_type = "unusually_high_vehicle_count"
            elif metrics.incident_rate_per_100veh_km > 5:
                metrics.anomaly_detected = True
                metrics.anomaly_type = "high_incident_rate"
            elif metrics.speed_violation_pct > 20:
                metrics.anomaly_detected = True
                metrics.anomaly_type = "excessive_speed_violations"

        return metrics

    def _update_history(
        self,
        global_metrics: _GlobalMetrics,
        zones: list[_ZoneMetrics],
    ) -> None:
        """Update rolling history for trend analysis."""
        self._vehicle_count_history.append(global_metrics.total_vehicles)
        self._avg_speed_history.append(global_metrics.avg_speed_cms)
        self._congestion_zone_history.append(global_metrics.congested_zones)
        self._incident_history.append(self._incidents_this_interval)

        # Keep only last 20 entries for trend analysis
        max_history = 20
        if len(self._vehicle_count_history) > max_history:
            self._vehicle_count_history = self._vehicle_count_history[-max_history:]
            self._avg_speed_history = self._avg_speed_history[-max_history:]
            self._congestion_zone_history = self._congestion_zone_history[-max_history:]
            self._incident_history = self._incident_history[-max_history:]



    # ── internal: conclusions generation ─────────────────────────────────────

    def _generate_conclusions(
        self,
        global_metrics: _GlobalMetrics,
        business_metrics: _BusinessAnalytics,
    ) -> dict:
        """
        Generate human-readable conclusions summarizing key findings.
        Designed to be passed to UrbanQA LLM for recommendation generation.
        """
        conclusions = {
            "congestion_status": self._assess_congestion(global_metrics, business_metrics),
            "incident_assessment": self._assess_incidents(business_metrics),
            "efficiency_summary": self._assess_efficiency(business_metrics),
            "risk_profile": self._assess_risk(business_metrics),
            "key_findings": self._generate_key_findings(global_metrics, business_metrics),
        }
        return conclusions

    def _build_llm_prompt(self, conclusions: dict) -> str:
        """Build a compact Groq prompt from the analytics conclusions."""
        prompt_lines = [
            "You are an expert urban mobility and real estate solutions analyst.",
            "Act as both a traffic systems specialist and a real estate development advisor.",
            "Read the conclusions below and produce one concise actionable solution.",
            "Return the answer as a single valid JSON object with these fields:",
            "  title, summary, category, urgency, impact, action, rationale",
            "Keep all values short and suitable for display in Unreal Engine.",
            "Do not include any markdown, explanation, or analysis outside the JSON.",
            "",
            "Conclusions:",
        ]
        for key, value in conclusions.items():
            prompt_lines.append(f"- {key}: {json.dumps(value)}")
        prompt_lines.append("")
        prompt_lines.append("JSON:")
        return "\n".join(prompt_lines)

    def _parse_grok_json(self, text: str) -> dict | None:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) > 2 and lines[-1].startswith("```"):
                text = "\n".join(lines[1:-1])
            else:
                text = "\n".join(lines[1:])

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end+1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _query_grok_solution(self, conclusions: dict) -> dict | str:
        """Send conclusions to the Groq API and return a structured solution."""
        if not self.grok_api_key:
            _log("Grok API key not configured; skipping LLM solution generation.")
            return {}

        prompt = self._build_llm_prompt(conclusions)
        body = {
            "model": self.grok_model,
            "messages": [
                {"role": "system", "content": "You are a helpful urban traffic analytics assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 220,
        }
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.grok_api_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.grok_api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.grok_timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                choice = payload.get("choices", [{}])[0]
                message = choice.get("message") or {}
                content = message.get("content") or payload.get("text") or ""
                content = content.strip()
                parsed = self._parse_grok_json(content)
                if parsed:
                    return parsed
                return {"summary": content}
        except urllib.error.HTTPError as exc:
            _log(f"Grok API HTTP error: {exc.code} {exc.reason}")
        except urllib.error.URLError as exc:
            _log(f"Grok API URL error: {exc.reason}")
        except Exception as exc:
            _log(f"Grok API request failed: {exc}")
        return {}

    def _assess_congestion(
        self,
        global_metrics: _GlobalMetrics,
        business_metrics: _BusinessAnalytics,
    ) -> dict:
        """Assess and describe congestion status."""
        congestion_pct = (
            (global_metrics.congested_zones / max(1, global_metrics.active_zones)) * 100
        )
        
        if congestion_pct >= 75:
            status = "critical"
            description = "Network experiencing severe congestion across most zones"
        elif congestion_pct >= 50:
            status = "high"
            description = "Significant congestion affecting multiple zones"
        elif congestion_pct >= 25:
            status = "moderate"
            description = "Some congestion in isolated zones"
        else:
            status = "low"
            description = "Network flowing smoothly with minimal congestion"

        return {
            "status": status,
            "description": description,
            "congested_zones": global_metrics.congested_zones,
            "total_zones": global_metrics.active_zones,
            "congestion_percentage": congestion_pct,
            "avg_speed_cms": global_metrics.avg_speed_cms,
            "trend": business_metrics.congestion_trend,
        }

    def _assess_incidents(self, business_metrics: _BusinessAnalytics) -> dict:
        """Assess incident trends and severity."""
        if business_metrics.incident_rate_per_100veh_km > 5:
            severity = "high"
            description = "Elevated incident rate detected"
        elif business_metrics.incident_rate_per_100veh_km > 2:
            severity = "moderate"
            description = "Moderate incident activity"
        else:
            severity = "low"
            description = "Incident rate within normal range"

        return {
            "severity": severity,
            "description": description,
            "incident_rate_per_100veh_km": business_metrics.incident_rate_per_100veh_km,
            "avg_incident_severity": business_metrics.avg_incident_severity,
            "trend": business_metrics.incident_trend,
            "high_risk_zones": business_metrics.high_risk_zone_count,
        }

    def _assess_efficiency(self, business_metrics: _BusinessAnalytics) -> dict:
        """Assess network efficiency metrics."""
        throughput = business_metrics.throughput_veh_per_min
        utilization = business_metrics.network_utilization_pct
        delay = business_metrics.avg_travel_delay_sec

        if utilization > 80 and delay > 10:
            efficiency_level = "poor"
        elif utilization > 60 or delay > 5:
            efficiency_level = "fair"
        else:
            efficiency_level = "good"

        return {
            "efficiency_level": efficiency_level,
            "throughput_veh_per_min": throughput,
            "network_utilization_pct": utilization,
            "avg_travel_delay_sec": delay,
            "peak_hour_detected": business_metrics.peak_hour_detected,
            "vehicle_distribution_balance": business_metrics.vehicle_distribution_balance,
        }

    def _assess_risk(self, business_metrics: _BusinessAnalytics) -> dict:
        """Assess overall risk profile."""
        risk_score = 0

        # Congestion risk
        congestion_risk_pct = (
            (1 - business_metrics.avg_acceleration_cms2 / 5000) * 100
        )
        if congestion_risk_pct > 70:
            risk_score += 25

        # Incident risk
        if business_metrics.incident_rate_per_100veh_km > 3:
            risk_score += 20

        # Speed compliance risk
        if business_metrics.speed_violation_pct > 15:
            risk_score += 15

        # Peak hour risk
        if business_metrics.peak_hour_detected:
            risk_score += 10

        # Environmental risk (emissions)
        if business_metrics.estimated_co2_emissions_kg > 500:
            risk_score += 10

        risk_level = "low" if risk_score < 25 else (
            "medium" if risk_score < 50 else "high"
        )

        return {
            "risk_score": min(100, risk_score),
            "risk_level": risk_level,
            "speed_violation_pct": business_metrics.speed_violation_pct,
            "estimated_co2_emissions_kg": business_metrics.estimated_co2_emissions_kg,
            "anomaly_detected": business_metrics.anomaly_detected,
            "anomaly_type": business_metrics.anomaly_type if business_metrics.anomaly_detected else None,
        }

    def _generate_key_findings(
        self,
        global_metrics: _GlobalMetrics,
        business_metrics: _BusinessAnalytics,
    ) -> list[str]:
        """Generate top-level key findings for decision-making."""
        findings = []

        # Finding 1: Network capacity
        if business_metrics.peak_hour_detected:
            findings.append(
                f"Peak hour detected: {global_metrics.total_vehicles} vehicles on network, "
                f"utilization at {business_metrics.network_utilization_pct:.1f}%"
            )
        else:
            findings.append(
                f"{global_metrics.total_vehicles} vehicles on network with "
                f"{business_metrics.network_utilization_pct:.1f}% utilization"
            )

        # Finding 2: Speed & congestion
        if global_metrics.congested_zones > 0:
            findings.append(
                f"Congestion in {global_metrics.congested_zones}/{global_metrics.active_zones} zones; "
                f"avg speed {global_metrics.avg_speed_cms:.0f}cm/s, trend: {business_metrics.congestion_trend}"
            )

        # Finding 3: Safety & compliance
        if business_metrics.speed_violation_pct > 10 or business_metrics.incident_rate_per_100veh_km > 2:
            findings.append(
                f"Safety concern: {business_metrics.speed_violation_pct:.1f}% speed violations, "
                f"{business_metrics.incident_rate_per_100veh_km:.2f} incidents/100veh·km, "
                f"trend: {business_metrics.incident_trend}"
            )

        # Finding 4: Economic impact
        if business_metrics.congestion_economic_cost_usd > 0:
            findings.append(
                f"Economic impact: ${business_metrics.congestion_economic_cost_usd:.2f} in congestion costs; "
                f"CO₂ emissions: {business_metrics.estimated_co2_emissions_kg:.1f}kg"
            )

        # Finding 5: Distribution & balance
        if business_metrics.vehicle_distribution_balance < 0.7:
            findings.append(
                f"Vehicle distribution imbalance detected: {business_metrics.vehicle_distribution_balance:.2f} "
                f"({business_metrics.high_risk_zone_count} high-risk zones)"
            )

        # Finding 6: Anomalies
        if business_metrics.anomaly_detected:
            findings.append(
                f"Anomaly detected: {business_metrics.anomaly_type}"
            )

        return findings if findings else ["Network operating within normal parameters"]

    # ── internal: report generation ───────────────────────────────────────────

    def _generate_report(
        self,
        vehicles: list[dict],
        sim_time: float,
        step: int,
    ) -> list[AgentEvent]:
        """Generate comprehensive analytics report."""
        events: list[AgentEvent] = []

        # ── Global metrics ────────────────────────────────────────────────
        if vehicles:
            speeds = [float(v.get("speed", 0.0)) for v in vehicles]
            global_metrics = _GlobalMetrics(
                timestamp=sim_time,
                total_vehicles=len(vehicles),
                avg_speed_cms=sum(speeds) / len(speeds) if speeds else 0.0,
                max_speed_cms=max(speeds) if speeds else 0.0,
                min_speed_cms=min(speeds) if speeds else 0.0,
                total_distance_cm=sum(
                    s.total_distance_cm for s in self._vehicle_snapshots.values()
                ),
                active_zones=0,
                congested_zones=0,
                incidents_this_interval=self._incidents_this_interval,
            )
        else:
            global_metrics = _GlobalMetrics(
                timestamp=sim_time,
                total_vehicles=0,
                avg_speed_cms=0.0,
                max_speed_cms=0.0,
                min_speed_cms=0.0,
                total_distance_cm=0.0,
                active_zones=0,
                congested_zones=0,
                incidents_this_interval=0,
            )

        # ── Zone metrics ──────────────────────────────────────────────────
        zones = self._detect_zones(vehicles)
        global_metrics.active_zones = len(zones)
        global_metrics.congested_zones = sum(1 for z in zones if z.is_congested)
        
        # ── Business Analytics ────────────────────────────────────────────
        business_metrics = self._calculate_business_analytics(
            vehicles, zones, global_metrics
        )
        self._update_history(global_metrics, zones)

        # ── Generate Conclusions ──────────────────────────────────────────
        conclusions = self._generate_conclusions(global_metrics, business_metrics)
        llm_solution = self._query_grok_solution(conclusions)

        # ── Build main analytics event ────────────────────────────────────
        snapshot_event = self.emit(
            type="analytics_snapshot",
            severity="info",
            msg=f"{global_metrics.total_vehicles} vehicles, "
            f"{global_metrics.active_zones} zones, "
            f"avg_speed={global_metrics.avg_speed_cms:.0f}cm/s",
            x=0.0,
            y=0.0,
            # Include full metrics as data
            global_vehicles=global_metrics.total_vehicles,
            global_avg_speed_cms=global_metrics.avg_speed_cms,
            global_max_speed_cms=global_metrics.max_speed_cms,
            global_min_speed_cms=global_metrics.min_speed_cms,
            global_total_distance_cm=global_metrics.total_distance_cm,
            active_zones=global_metrics.active_zones,
            congested_zones=global_metrics.congested_zones,
            incidents_this_interval=global_metrics.incidents_this_interval,
            # Include conclusions for LLM
            conclusions=conclusions,
        )
        events.append(snapshot_event)

        if llm_solution:
            if isinstance(llm_solution, dict):
                summary = llm_solution.get("summary") or llm_solution.get("title") or llm_solution.get("action") or "LLM solution available"
                events.append(
                    self.emit(
                        type="analytics_llm_solution",
                        severity="info",
                        msg=summary,
                        x=0.0,
                        y=0.0,
                        source="grok",
                        solution=llm_solution,
                        conclusions=conclusions,
                    )
                )
            else:
                events.append(
                    self.emit(
                        type="analytics_llm_solution",
                        severity="info",
                        msg=str(llm_solution),
                        x=0.0,
                        y=0.0,
                        source="grok",
                        solution_text=str(llm_solution),
                        conclusions=conclusions,
                    )
                )

        # Persist latest analytics snapshot in memory only
        try:
            latest_payload = {
                "timestamp": global_metrics.timestamp,
                "snapshot": snapshot_event.to_dict(),
                "conclusions": conclusions,
            }
            if isinstance(llm_solution, dict) and llm_solution:
                latest_payload["solution"] = llm_solution
            elif llm_solution:
                latest_payload["solution_text"] = str(llm_solution)
            set_latest(latest_payload)
        except Exception as exc:
            _log(f"Failed to store latest analytics in memory: {exc}")

        # ── Zone details ──────────────────────────────────────────────────
        for zone in zones:
            zone_event = self.emit(
                type="zone_analytics",
                severity="warning" if zone.is_congested else "info",
                msg=f"Zone {zone.zone_id}: {zone.vehicle_count} vehicles, "
                f"avg_speed={zone.avg_speed_cms:.0f}cm/s, "
                f"density={zone.density_vehicles_per_sqkm:.1f} veh/km²",
                x=zone.cx,
                y=zone.cy,
                zone_id=zone.zone_id,
                zone_center_x=zone.cx,
                zone_center_y=zone.cy,
                zone_vehicle_count=zone.vehicle_count,
                zone_avg_speed_cms=zone.avg_speed_cms,
                zone_density=zone.density_vehicles_per_sqkm,
                zone_vehicle_ids=zone.vehicle_ids,
                is_congested=zone.is_congested,
            )
            events.append(zone_event)
        
        # ── Business Analytics Event ──────────────────────────────────────
        business_event = self.emit(
            type="business_analytics",
            severity="info",
            msg=f"Operational Efficiency: {business_metrics.network_utilization_pct:.1f}% utilization, "
            f"{business_metrics.throughput_veh_per_min:.1f} veh/min | "
            f"Economic Impact: ${business_metrics.congestion_economic_cost_usd:.2f} in congestion costs | "
            f"Safety: {business_metrics.incident_rate_per_100veh_km:.2f} incidents/100veh·km",
            x=0.0,
            y=0.0,
            # Operational Efficiency
            throughput_veh_per_min=business_metrics.throughput_veh_per_min,
            avg_travel_delay_sec=business_metrics.avg_travel_delay_sec,
            congestion_cost_index=business_metrics.congestion_cost_index,
            network_utilization_pct=business_metrics.network_utilization_pct,
            # Safety & Risk
            incident_rate_per_100veh_km=business_metrics.incident_rate_per_100veh_km,
            avg_incident_severity=business_metrics.avg_incident_severity,
            high_risk_zone_count=business_metrics.high_risk_zone_count,
            speed_violation_pct=business_metrics.speed_violation_pct,
            # Economic Impact
            estimated_fuel_consumption_l=business_metrics.estimated_fuel_consumption_l,
            estimated_co2_emissions_kg=business_metrics.estimated_co2_emissions_kg,
            time_lost_to_congestion_veh_hrs=business_metrics.time_lost_to_congestion_veh_hrs,
            congestion_economic_cost_usd=business_metrics.congestion_economic_cost_usd,
            # Demand & Capacity
            peak_hour_detected=business_metrics.peak_hour_detected,
            utilization_ratio=business_metrics.utilization_ratio,
            bottleneck_severity_score=business_metrics.bottleneck_severity_score,
            vehicle_distribution_balance=business_metrics.vehicle_distribution_balance,
            # Vehicle Performance
            avg_acceleration_cms2=business_metrics.avg_acceleration_cms2,
            harsh_acceleration_events=business_metrics.harsh_acceleration_events,
            speed_limit_compliance_pct=business_metrics.speed_limit_compliance_pct,
            tire_wear_index=business_metrics.tire_wear_index,
            # Predictive Insights
            congestion_trend=business_metrics.congestion_trend,
            incident_trend=business_metrics.incident_trend,
            anomaly_detected=business_metrics.anomaly_detected,
            anomaly_type=business_metrics.anomaly_type,
        )
        events.append(business_event)

        _log(
            f"Report: {global_metrics.total_vehicles} vehicles, "
            f"{len(zones)} zones, {global_metrics.congested_zones} congested"
        )

        return events

    # ── public methods ────────────────────────────────────────────────────────

    def record_incident(self, incident_type: str) -> None:
        """
        Called by external code to record an incident occurrence.
        (e.g., from another agent when it detects something)
        """
        self._incident_count_by_type[incident_type] = (
            self._incident_count_by_type.get(incident_type, 0) + 1
        )
        self._incidents_this_interval += 1

    def record_agent_event(self, agent_name: str) -> None:
        """Track events emitted by other agents."""
        self._events_per_agent[agent_name] = (
            self._events_per_agent.get(agent_name, 0) + 1
        )

    def get_vehicle_stats(self, vehicle_id: str) -> dict | None:
        """Retrieve per-vehicle cumulative statistics."""
        snap = self._vehicle_snapshots.get(str(vehicle_id))
        if not snap:
            return None
        return {
            "id": snap.id,
            "total_distance_cm": snap.total_distance_cm,
            "max_speed_cms": snap.max_speed_cms,
            "min_speed_cms": snap.min_speed_cms,
            "tick_count": snap.tick_count,
            "current_speed_cms": snap.speed_cms,
        }

    def get_global_stats(self) -> dict:
        """Get cumulative global statistics."""
        return {
            "total_ticks_monitored": self._total_ticks_monitored,
            "total_vehicles_tracked": len(self._vehicle_snapshots),
            "incident_count_by_type": self._incident_count_by_type,
            "events_per_agent": self._events_per_agent,
        }

    def get_business_summary(self) -> dict:
        """
        Get a human-readable summary of business metrics for decision-making.
        Provides actionable insights for managers and planners.
        """
        return {
            "operational_efficiency": {
                "network_utilization_pct": f"{self._vehicle_count_history[-1] / 500 * 100:.1f}%"
                if self._vehicle_count_history
                else "0%",
                "description": "How full the network is relative to capacity",
            },
            "safety_insights": {
                "recent_incidents": sum(self._incident_history[-3:])
                if self._incident_history
                else 0,
                "incident_trend": "improving" if len(self._incident_history) >= 2 and self._incident_history[-1] < self._incident_history[-2] else "worsening"
                if len(self._incident_history) >= 2 and self._incident_history[-1] > self._incident_history[-2]
                else "stable",
            },
            "congestion_analysis": {
                "current_congestion": self._congestion_zone_history[-1]
                if self._congestion_zone_history
                else 0,
                "trend": "getting_better" if len(self._congestion_zone_history) >= 2 and self._congestion_zone_history[-1] < self._congestion_zone_history[-2] else "getting_worse"
                if len(self._congestion_zone_history) >= 2 and self._congestion_zone_history[-1] > self._congestion_zone_history[-2]
                else "stable",
            },
            "actionable_recommendations": self._generate_recommendations(),
        }

    def _generate_recommendations(self) -> list[str]:
        """Generate actionable recommendations based on current state."""
        recommendations = []

        # Check congestion trend
        if (
            len(self._congestion_zone_history) >= 3
            and self._congestion_zone_history[-1]
            > sum(self._congestion_zone_history[-3:-1]) / 2
        ):
            recommendations.append(
                "Congestion is increasing - consider deploying adaptive signal control"
            )

        # Check incident rate
        if sum(self._incident_history[-3:]) > 5 if self._incident_history else False:
            recommendations.append(
                "High incident rate detected - review safety protocols in hotspots"
            )

        # Check speed violations
        total_violations = sum(self._speed_violations.values())
        if total_violations > 100:
            recommendations.append(
                "Excessive speeding detected - increase traffic enforcement"
            )

        # Check vehicle distribution
        if len(self._vehicle_count_history) >= 2:
            if (
                self._vehicle_count_history[-1]
                > self._vehicle_count_history[-2] * 1.3
            ):
                recommendations.append(
                    "Sudden traffic surge - activate overflow routes"
                )

        if not recommendations:
            recommendations.append("Network operating normally - maintain current strategies")

        return recommendations

    def __repr__(self) -> str:
        return (
            f"<AnalyticsAgent "
            f"vehicles_tracked={len(self._vehicle_snapshots)} "
            f"ticks={self._total_ticks_monitored} "
            f"business_events_tracked={len(self._incident_count_by_type)}>"
        )
