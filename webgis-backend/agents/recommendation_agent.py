"""
agents/recommendation_agent.py
──────────────────────────────
Recommendation Agent — developer-focused urban planning insights.

Analyzes traffic analytics to provide real estate developers with actionable
recommendations for:
  • High-value development zones (accessibility + low congestion)
  • Mixed-use development opportunities
  • Infrastructure improvement needs
  • Transit-oriented development potential
  • Economic feasibility analysis per zone
  • Risk mitigation strategies

Emitted event types
───────────────────
  "dev_zone_recommendation"  — development opportunity in a specific zone
  "dev_infrastructure_need"  — infrastructure gap identified
  "dev_risk_alert"          — risk factor for development planning
  "dev_market_summary"      — quarterly market insights for decision-makers

Constructor arguments (all have defaults)
─────────────────────────────────────────
  analysis_interval_ticks    : ticks between recommendations (default 1000 = ~20s @ 50Hz)
  min_zone_vehicles          : minimum vehicles in zone to analyze (default 5)
  congestion_threshold_cms   : speed threshold for congestion (default 500 cm/s = 5 m/s)
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from .base_agent import BaseAgent, AgentEvent

log_enabled = False  # Set to True for debug output


def _log(msg: str):
    if log_enabled:
        print(f"[RecommendationAgent] {msg}")


@dataclass
class _ZoneOpportunity:
    """Represents a development opportunity in a zone."""
    zone_id: str
    center_x: float
    center_y: float
    vehicle_count: int
    avg_speed_cms: float
    density_vehicles_per_sqkm: float
    is_congested: bool
    
    # Developer metrics
    accessibility_score: float = 0.0  # 0-100, higher = better access
    congestion_risk: float = 0.0      # 0-100, higher = more risk
    development_viability: float = 0.0 # 0-100, higher = better opportunity
    recommended_use: str = ""  # residential, commercial, mixed-use, industrial
    estimated_real_estate_value: float = 0.0  # USD per sq km


@dataclass
class _DeveloperInsight:
    """Structured developer insight for decision-making."""
    insight_type: str  # opportunity, risk, improvement, trend
    location: tuple[float, float]  # (x, y)
    description: str
    priority: str  # high, medium, low
    estimated_impact_pct: float  # Expected improvement %
    investment_level: str  # low, medium, high
    payback_period_years: float


@dataclass
class _MarketQuarter:
    """Quarterly market analysis snapshot."""
    quarter_num: int
    avg_accessibility_score: float
    total_opportunities_count: int
    high_value_zones_count: int
    infrastructure_needs: list[str]
    estimated_total_opportunity_usd: float
    risk_factors: list[str]
    market_trend: str  # bullish, neutral, bearish


@dataclass
class _Solution:
    """Actionable solution for a specific problem."""
    solution_id: str
    problem_type: str  # congestion, accessibility, safety, livability, demand
    zone_id: str
    location: tuple[float, float]  # (x, y)
    title: str
    description: str
    priority: str  # high, medium, low
    estimated_cost_usd: float
    estimated_timeframe_months: int
    expected_benefit: str  # e.g., "Reduce congestion by 30%"
    expected_impact_pct: float  # 0-100
    implementation_steps: list[str]
    responsible_party: str  # developer, city_planning, traffic_management
    success_metrics: list[str]
    dependencies: list[str] = field(default_factory=list)  # Other solutions this depends on


class RecommendationAgent(BaseAgent):
    """
    Developer-focused recommendation engine for urban planning.
    Translates traffic analytics into real estate opportunities and risks.
    """

    def __init__(
        self,
        analysis_interval_ticks: int = 1000,
        min_zone_vehicles: int = 5,
        congestion_threshold_cms: float = 500.0,
    ):
        super().__init__(name="RecommendationAgent")
        self.analysis_interval_ticks = analysis_interval_ticks
        self.min_zone_vehicles = min_zone_vehicles
        self.congestion_threshold_cms = congestion_threshold_cms

        # ── historical tracking ───────────────────────────────────────────
        self._zone_history: dict[str, list[_ZoneOpportunity]] = {}
        self._opportunities_by_zone: dict[str, _ZoneOpportunity] = {}
        self._infrastructure_gaps: dict[str, dict] = {}
        self._risk_zones: dict[str, float] = {}  # zone_id -> risk_score
        self._market_quarters: list[_MarketQuarter] = []

        # ── interval tracking ──────────────────────────────────────────
        self._ticks_since_analysis: int = 0
        self._total_analysis_cycles: int = 0

        # ── analytics cache ────────────────────────────────────────────
        self._last_business_metrics: dict = {}
        self._last_zones_analyzed: list[dict] = []
        
        # ── solutions tracking ─────────────────────────────────────────
        self._generated_solutions: dict[str, _Solution] = {}
        self._solution_counter: int = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        super().on_start()
        print(
            f"[{self.name}] started — "
            f"analysis every {self.analysis_interval_ticks} ticks, "
            f"min_zone_vehicles={self.min_zone_vehicles}"
        )

    def on_stop(self) -> None:
        print(
            f"[{self.name}] summary — "
            f"analysis cycles: {self._total_analysis_cycles}, "
            f"zones evaluated: {len(self._opportunities_by_zone)}, "
            f"market quarters: {len(self._market_quarters)}"
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
        Analyze zones and generate recommendations periodically.
        """
        events: list[AgentEvent] = []

        self._ticks_since_analysis += 1

        # Check if time to analyze
        if self._ticks_since_analysis >= self.analysis_interval_ticks:
            analysis_events = self._generate_recommendations(vehicles, sim_time, step)
            events.extend(analysis_events)
            self._ticks_since_analysis = 0
            self._total_analysis_cycles += 1

        return events

    # ── internal: analysis ────────────────────────────────────────────────────

    def _analyze_zone_opportunity(
        self,
        zone_id: str,
        center_x: float,
        center_y: float,
        vehicle_count: int,
        avg_speed_cms: float,
        density_vehicles_per_sqkm: float,
        is_congested: bool,
    ) -> _ZoneOpportunity:
        """
        Convert zone analytics into developer opportunity metrics.
        """
        opp = _ZoneOpportunity(
            zone_id=zone_id,
            center_x=center_x,
            center_y=center_y,
            vehicle_count=vehicle_count,
            avg_speed_cms=avg_speed_cms,
            density_vehicles_per_sqkm=density_vehicles_per_sqkm,
            is_congested=is_congested,
        )

        # ─ Accessibility Score (0-100) ────────────────────────────────────
        # High traffic = high accessibility, but not if congested
        if is_congested:
            accessibility = (vehicle_count / 100) * 50  # Max 50 if congested
        else:
            accessibility = min(100.0, (vehicle_count / 50) * 100)
        opp.accessibility_score = accessibility

        # ─ Congestion Risk (0-100) ────────────────────────────────────────
        # Slow speed = high risk
        speed_ratio = avg_speed_cms / 5000.0  # 5000 = max speed ~50 m/s
        opp.congestion_risk = max(0.0, (1.0 - speed_ratio) * 100.0)

        # ─ Development Viability (0-100) ──────────────────────────────────
        # Balance: high accessibility + low congestion risk
        opp.development_viability = (
            (opp.accessibility_score * 0.6) + ((100 - opp.congestion_risk) * 0.4)
        )

        # ─ Recommended Use Type ───────────────────────────────────────────
        if density_vehicles_per_sqkm > 150:
            if is_congested:
                opp.recommended_use = "commercial_retail"  # High foot traffic
                opp.estimated_real_estate_value = 5000000  # $5M/sq km
            else:
                opp.recommended_use = "mixed_use"  # Balanced traffic
                opp.estimated_real_estate_value = 6500000  # $6.5M/sq km
        elif density_vehicles_per_sqkm > 50:
            if is_congested:
                opp.recommended_use = "residential_metro"  # Transit-oriented
                opp.estimated_real_estate_value = 4000000  # $4M/sq km
            else:
                opp.recommended_use = "residential_suburban"
                opp.estimated_real_estate_value = 2500000  # $2.5M/sq km
        else:
            opp.recommended_use = "industrial_logistics"  # Lower density
            opp.estimated_real_estate_value = 800000  # $800K/sq km

        return opp

    def _detect_infrastructure_gaps(
        self,
        zones: list[_ZoneOpportunity],
    ) -> dict[str, dict]:
        """
        Identify infrastructure improvements needed for development potential.
        """
        gaps = {}

        for zone in zones:
            zone_gaps = []

            # Check for public transport need
            if zone.accessibility_score > 70 and zone.density_vehicles_per_sqkm > 100:
                zone_gaps.append({
                    "type": "public_transit",
                    "priority": "high",
                    "description": "High accessibility zone needs metro/bus integration",
                    "estimated_cost_usd": 5000000,
                })

            # Check for congestion mitigation
            if zone.congestion_risk > 60 and zone.vehicle_count > 10:
                zone_gaps.append({
                    "type": "traffic_optimization",
                    "priority": "high",
                    "description": "Congestion mitigation needed - signal optimization or bypass roads",
                    "estimated_cost_usd": 2000000,
                })

            # Check for parking infrastructure
            if zone.recommended_use in ["commercial_retail", "mixed_use"]:
                zone_gaps.append({
                    "type": "parking_infrastructure",
                    "priority": "medium",
                    "description": "Multi-level parking or underground parking recommended",
                    "estimated_cost_usd": 3000000,
                })

            # Check for green space
            if zone.density_vehicles_per_sqkm > 100:
                zone_gaps.append({
                    "type": "green_space",
                    "priority": "medium",
                    "description": "Urban parks and green corridors for livability",
                    "estimated_cost_usd": 1000000,
                })

            if zone_gaps:
                gaps[zone.zone_id] = {
                    "location": (zone.center_x, zone.center_y),
                    "gaps": zone_gaps,
                    "total_infrastructure_cost": sum(g["estimated_cost_usd"] for g in zone_gaps),
                }

        return gaps

    def _identify_risk_factors(
        self,
        zones: list[_ZoneOpportunity],
        business_metrics: dict,
    ) -> dict[str, float]:
        """
        Identify and score risk factors for development.
        """
        risks = {}

        for zone in zones:
            risk_score = 0.0

            # Congestion risk
            if zone.congestion_risk > 70:
                risk_score += 25  # High congestion reduces value

            # High incident rate
            if business_metrics.get("incident_rate_per_100veh_km", 0) > 3:
                risk_score += 20

            # Speed violations (safety risk)
            if business_metrics.get("speed_violation_pct", 0) > 15:
                risk_score += 15

            # Peak hour volatility
            if business_metrics.get("peak_hour_detected", False):
                risk_score += 10

            # Environmental concerns
            co2_emissions = business_metrics.get("estimated_co2_emissions_kg", 0)
            if co2_emissions > 500:
                risk_score += 10

            if risk_score > 0:
                risks[zone.zone_id] = min(100.0, risk_score)

        return risks

    def _calculate_market_quarter(
        self,
        zones: list[_ZoneOpportunity],
        business_metrics: dict,
    ) -> _MarketQuarter:
        """Calculate quarterly market summary for strategic planning."""
        quarter = _MarketQuarter(
            quarter_num=self._total_analysis_cycles // 4 + 1,
            avg_accessibility_score=0.0,
            total_opportunities_count=len(zones),
            high_value_zones_count=0,
            infrastructure_needs=[],
            estimated_total_opportunity_usd=0.0,
            risk_factors=[],
            market_trend="neutral",
        )

        if zones:
            quarter.avg_accessibility_score = (
                sum(z.accessibility_score for z in zones) / len(zones)
            )
            quarter.high_value_zones_count = sum(
                1 for z in zones if z.development_viability > 70
            )
            quarter.estimated_total_opportunity_usd = sum(
                z.estimated_real_estate_value for z in zones
            )

        # Identify infrastructure needs
        infra_gaps = self._detect_infrastructure_gaps(zones)
        for zone_id, info in infra_gaps.items():
            for gap in info["gaps"]:
                if gap not in quarter.infrastructure_needs:
                    quarter.infrastructure_needs.append(gap["type"])

        # Assess market trend
        if len(self._market_quarters) >= 2:
            prev_quarter = self._market_quarters[-1]
            if quarter.high_value_zones_count > prev_quarter.high_value_zones_count:
                quarter.market_trend = "bullish"
            elif quarter.high_value_zones_count < prev_quarter.high_value_zones_count:
                quarter.market_trend = "bearish"
            else:
                quarter.market_trend = "neutral"

        # Identify risk factors
        if business_metrics.get("incident_rate_per_100veh_km", 0) > 3:
            quarter.risk_factors.append("high_incident_rate")
        if business_metrics.get("anomaly_detected", False):
            quarter.risk_factors.append(f"anomaly: {business_metrics.get('anomaly_type', 'unknown')}")
        if business_metrics.get("congestion_trend") == "increasing":
            quarter.risk_factors.append("congestion_worsening")

        return quarter

    def _update_zone_history(
        self,
        zones: list[_ZoneOpportunity],
    ) -> None:
        """Maintain rolling history of zone opportunities."""
        for zone in zones:
            if zone.zone_id not in self._zone_history:
                self._zone_history[zone.zone_id] = []
            self._zone_history[zone.zone_id].append(zone)
            # Keep only last 10 snapshots
            if len(self._zone_history[zone.zone_id]) > 10:
                self._zone_history[zone.zone_id] = self._zone_history[zone.zone_id][-10:]

    # ── internal: solution generation ─────────────────────────────────────────

    def _generate_solution_for_congestion(
        self,
        zone: _ZoneOpportunity,
        business_metrics: dict,
    ) -> list[_Solution]:
        """Generate solutions for congestion problems."""
        solutions = []

        if zone.congestion_risk < 60:
            return solutions  # No severe congestion

        # Solution 1: Smart Traffic Signal Control
        solution1 = _Solution(
            solution_id=f"SOL_{self._solution_counter:03d}",
            problem_type="congestion",
            zone_id=zone.zone_id,
            location=(zone.center_x, zone.center_y),
            title="Adaptive Traffic Signal Control System",
            description="Deploy AI-powered traffic signals that adjust timing based on real-time vehicle flow",
            priority="high",
            estimated_cost_usd=1500000,
            estimated_timeframe_months=6,
            expected_benefit="Reduce congestion by 25-30%",
            expected_impact_pct=28.0,
            implementation_steps=[
                "1. Survey existing signal infrastructure",
                "2. Install IoT sensors at key intersections",
                "3. Deploy AI traffic management software",
                "4. Calibrate and test system",
                "5. Full deployment and optimization"
            ],
            responsible_party="city_planning",
            success_metrics=[
                "Average intersection wait time reduced by 30%",
                "Traffic throughput increased by 25%",
                "Fuel consumption reduced by 20%",
                "Emissions reduced by 18%"
            ],
            dependencies=[]
        )
        solutions.append(solution1)
        self._solution_counter += 1

        # Solution 2: Bypass/Alternative Routes
        solution2 = _Solution(
            solution_id=f"SOL_{self._solution_counter:03d}",
            problem_type="congestion",
            zone_id=zone.zone_id,
            location=(zone.center_x, zone.center_y),
            title="Develop Bypass Road Network",
            description="Create alternative routes that divert traffic around congestion hotspots",
            priority="high",
            estimated_cost_usd=8500000,
            estimated_timeframe_months=24,
            expected_benefit="Reduce congestion by 35-40%",
            expected_impact_pct=38.0,
            implementation_steps=[
                "1. Traffic flow analysis and route modeling",
                "2. Land acquisition and environmental approvals",
                "3. Detailed engineering design",
                "4. Phase 1: Construction of primary bypass",
                "5. Phase 2: Secondary connections",
                "6. Integration with existing network"
            ],
            responsible_party="city_planning",
            success_metrics=[
                "Peak hour congestion reduced by 40%",
                "Average commute time reduced by 25%",
                "Main corridor traffic volume reduced by 35%"
            ],
            dependencies=[]
        )
        solutions.append(solution2)
        self._solution_counter += 1

        # Solution 3: Public Transit Enhancement
        if zone.accessibility_score > 60:
            solution3 = _Solution(
                solution_id=f"SOL_{self._solution_counter:03d}",
                problem_type="congestion",
                zone_id=zone.zone_id,
                location=(zone.center_x, zone.center_y),
                title="Expand Public Transportation",
                description="Add metro lines, bus rapid transit, or light rail to reduce car dependency",
                priority="high",
                estimated_cost_usd=5200000,
                estimated_timeframe_months=30,
                expected_benefit="Reduce private vehicle traffic by 20-25%",
                expected_impact_pct=23.0,
                implementation_steps=[
                    "1. Route planning and feasibility study",
                    "2. Environmental and social impact assessment",
                    "3. Procurement of vehicles/equipment",
                    "4. Station/infrastructure construction",
                    "5. System testing and staff training",
                    "6. Public launch and optimization"
                ],
                responsible_party="city_planning",
                success_metrics=[
                    "Reduce vehicle trips by 25%",
                    "Increase transit ridership by 40%",
                    "Improve air quality by 15%",
                    "Reduce congestion cost by 30%"
                ],
                dependencies=[f"SOL_{self._solution_counter - 2:03d}"]  # Depends on signal control
            )
            solutions.append(solution3)
            self._solution_counter += 1

        return solutions

    def _generate_solution_for_accessibility(
        self,
        zone: _ZoneOpportunity,
    ) -> list[_Solution]:
        """Generate solutions for accessibility problems."""
        solutions = []

        if zone.accessibility_score > 60:
            return solutions  # Accessibility is good

        # Solution: Improve Connectivity
        solution = _Solution(
            solution_id=f"SOL_{self._solution_counter:03d}",
            problem_type="accessibility",
            zone_id=zone.zone_id,
            location=(zone.center_x, zone.center_y),
            title="Enhanced Road Network Connectivity",
            description="Improve road quality, add new connections, improve pedestrian/cycling infrastructure",
            priority="medium",
            estimated_cost_usd=2800000,
            estimated_timeframe_months=18,
            expected_benefit="Increase accessibility score by 25-30%",
            expected_impact_pct=28.0,
            implementation_steps=[
                "1. Network assessment and planning",
                "2. Identify critical connectivity gaps",
                "3. Road widening and resurfacing",
                "4. Add bike lanes and pedestrian pathways",
                "5. Install way-finding signage",
                "6. Community engagement and feedback"
            ],
            responsible_party="city_planning",
            success_metrics=[
                "Average travel distance reduced by 20%",
                "Accessibility score increased by 30%",
                "Pedestrian/cyclist usage increased by 40%"
            ],
            dependencies=[]
        )
        solutions.append(solution)
        self._solution_counter += 1

        return solutions

    def _generate_solution_for_safety(
        self,
        zone: _ZoneOpportunity,
        business_metrics: dict,
    ) -> list[_Solution]:
        """Generate solutions for safety/compliance issues."""
        solutions = []

        speed_violation_pct = business_metrics.get("speed_violation_pct", 0)
        incident_rate = business_metrics.get("incident_rate_per_100veh_km", 0)

        if speed_violation_pct > 10:
            # Solution: Speed Enforcement
            solution = _Solution(
                solution_id=f"SOL_{self._solution_counter:03d}",
                problem_type="safety",
                zone_id=zone.zone_id,
                location=(zone.center_x, zone.center_y),
                title="Enhanced Speed Enforcement",
                description="Deploy automated speed cameras, traffic enforcement, and driver awareness campaigns",
                priority="high" if speed_violation_pct > 20 else "medium",
                estimated_cost_usd=1200000,
                estimated_timeframe_months=3,
                expected_benefit="Reduce speed violations by 40-50%",
                expected_impact_pct=45.0,
                implementation_steps=[
                    "1. Install speed detection cameras at hotspots",
                    "2. Setup automated fine system",
                    "3. Community awareness campaign",
                    "4. Increased police patrols",
                    "5. Regular monitoring and adjustment"
                ],
                responsible_party="traffic_management",
                success_metrics=[
                    "Speed violations reduced by 50%",
                    "Accident rate reduced by 25%",
                    "Average speed reduced by 5%"
                ],
                dependencies=[]
            )
            solutions.append(solution)
            self._solution_counter += 1

        if incident_rate > 2.5:
            # Solution: Safety Infrastructure
            solution = _Solution(
                solution_id=f"SOL_{self._solution_counter:03d}",
                problem_type="safety",
                zone_id=zone.zone_id,
                location=(zone.center_x, zone.center_y),
                title="Improve Safety Infrastructure",
                description="Add protective barriers, improve lighting, better road markings, and hazard warnings",
                priority="high",
                estimated_cost_usd=950000,
                estimated_timeframe_months=4,
                expected_benefit="Reduce incidents by 30-35%",
                expected_impact_pct=32.0,
                implementation_steps=[
                    "1. Safety audit of zone",
                    "2. Identify high-risk areas",
                    "3. Install protective barriers",
                    "4. Improve street lighting",
                    "5. Add warning signs and road markings",
                    "6. Safety awareness training"
                ],
                responsible_party="city_planning",
                success_metrics=[
                    "Incident rate reduced by 35%",
                    "Severe accidents reduced by 40%",
                    "Public safety perception improved"
                ],
                dependencies=[]
            )
            solutions.append(solution)
            self._solution_counter += 1

        return solutions

    def _generate_solution_for_development(
        self,
        zone: _ZoneOpportunity,
    ) -> list[_Solution]:
        """Generate solutions to enable development in a zone."""
        solutions = []

        # Solution 1: Infrastructure Package (depends on zone type)
        infra_description = {
            "commercial_retail": "Deploy parking structures, loading zones, and pedestrian amenities",
            "mixed_use": "Multi-level parking, public spaces, and mixed transportation options",
            "residential_metro": "Transit connections, pedestrian zones, and local services",
            "residential_suburban": "School and park integration, local services",
            "industrial_logistics": "Freight optimization, worker facilities, environmental controls"
        }

        description = infra_description.get(zone.recommended_use, "General infrastructure development")
        cost_mapping = {
            "commercial_retail": 4000000,
            "mixed_use": 5500000,
            "residential_metro": 3500000,
            "residential_suburban": 2000000,
            "industrial_logistics": 1500000
        }

        solution = _Solution(
            solution_id=f"SOL_{self._solution_counter:03d}",
            problem_type="development",
            zone_id=zone.zone_id,
            location=(zone.center_x, zone.center_y),
            title=f"Development Enablement: {zone.recommended_use.replace('_', ' ').title()}",
            description=description,
            priority="high" if zone.development_viability > 70 else "medium",
            estimated_cost_usd=cost_mapping.get(zone.recommended_use, 3000000),
            estimated_timeframe_months=18,
            expected_benefit=f"Enable {zone.recommended_use} development",
            expected_impact_pct=zone.development_viability,
            implementation_steps=[
                "1. Planning approval and zoning verification",
                "2. Environmental impact assessment",
                "3. Infrastructure upgrades",
                "4. Utility connections and setup",
                "5. Construction permits issued",
                "6. Development phase begins"
            ],
            responsible_party="developer",
            success_metrics=[
                f"Enable {zone.recommended_use} projects",
                "Attract developer interest",
                f"Generate real estate value of ${zone.estimated_real_estate_value:,.0f}/sq km",
                "Create employment opportunities"
            ],
            dependencies=[]
        )
        solutions.append(solution)
        self._solution_counter += 1

        return solutions

    def _generate_recommendations(
        self,
        vehicles: list[dict],
        sim_time: float,
        step: int,
    ) -> list[AgentEvent]:
        """Generate comprehensive developer recommendations."""
        events: list[AgentEvent] = []

        # For this demo, create synthetic zone opportunities from vehicle clusters
        zones = self._create_zone_opportunities_from_vehicles(vehicles)

        if not zones:
            return []

        self._last_zones_analyzed = zones
        self._update_zone_history(zones)

        # ── Generate zone recommendations ──────────────────────────────────
        for zone in zones:
            event = self.emit(
                type="dev_zone_recommendation",
                severity="info" if zone.development_viability > 60 else "warning",
                msg=f"Zone {zone.zone_id}: {zone.recommended_use.replace('_', ' ').title()} "
                f"- {zone.development_viability:.0f}% viability, "
                f"${zone.estimated_real_estate_value:,.0f}/sq km value",
                x=zone.center_x,
                y=zone.center_y,
                zone_id=zone.zone_id,
                recommended_use=zone.recommended_use,
                development_viability=zone.development_viability,
                accessibility_score=zone.accessibility_score,
                congestion_risk=zone.congestion_risk,
                estimated_real_estate_value=zone.estimated_real_estate_value,
                vehicle_count=zone.vehicle_count,
                avg_speed_cms=zone.avg_speed_cms,
                density_vehicles_per_sqkm=zone.density_vehicles_per_sqkm,
            )
            events.append(event)
            self._opportunities_by_zone[zone.zone_id] = zone

        # ── Infrastructure gap recommendations ────────────────────────────
        infra_gaps = self._detect_infrastructure_gaps(zones)
        for zone_id, info in infra_gaps.items():
            for gap in info["gaps"]:
                event = self.emit(
                    type="dev_infrastructure_need",
                    severity="warning" if gap["priority"] == "high" else "info",
                    msg=f"Zone {zone_id}: {gap['description']} "
                    f"(Est. cost: ${gap['estimated_cost_usd']:,})",
                    x=info["location"][0],
                    y=info["location"][1],
                    zone_id=zone_id,
                    infrastructure_type=gap["type"],
                    priority=gap["priority"],
                    estimated_cost=gap["estimated_cost_usd"],
                )
                events.append(event)

        # ── Risk alerts ───────────────────────────────────────────────────
        risks = self._identify_risk_factors(zones, self._last_business_metrics)
        for zone_id, risk_score in risks.items():
            if risk_score > 40:  # Only alert on significant risks
                zone = self._opportunities_by_zone.get(zone_id)
                if zone:
                    event = self.emit(
                        type="dev_risk_alert",
                        severity="warning" if risk_score > 60 else "info",
                        msg=f"Zone {zone_id}: Development risk score {risk_score:.0f}/100 - "
                        f"Recommend mitigation strategies",
                        x=zone.center_x,
                        y=zone.center_y,
                        zone_id=zone_id,
                        risk_score=risk_score,
                    )
                    events.append(event)
                    self._risk_zones[zone_id] = risk_score

        # ── Generate and emit solutions ────────────────────────────────────
        for zone in zones:
            # Congestion solutions
            congestion_solutions = self._generate_solution_for_congestion(
                zone, self._last_business_metrics
            )
            for solution in congestion_solutions:
                self._generated_solutions[solution.solution_id] = solution
                event = self.emit(
                    type="dev_solution_congestion",
                    severity="warning" if zone.congestion_risk > 70 else "info",
                    msg=f"Solution [{solution.priority.upper()}]: {solution.title} - "
                    f"Impact: {solution.expected_impact_pct:.0f}% | Cost: ${solution.estimated_cost_usd:,.0f} | "
                    f"Timeline: {solution.estimated_timeframe_months} months",
                    x=zone.center_x,
                    y=zone.center_y,
                    solution_id=solution.solution_id,
                    zone_id=solution.zone_id,
                    title=solution.title,
                    description=solution.description,
                    priority=solution.priority,
                    cost=solution.estimated_cost_usd,
                    timeframe_months=solution.estimated_timeframe_months,
                    expected_impact_pct=solution.expected_impact_pct,
                    expected_benefit=solution.expected_benefit,
                    implementation_steps=solution.implementation_steps,
                    responsible_party=solution.responsible_party,
                    success_metrics=solution.success_metrics,
                )
                events.append(event)

            # Accessibility solutions
            access_solutions = self._generate_solution_for_accessibility(zone)
            for solution in access_solutions:
                self._generated_solutions[solution.solution_id] = solution
                event = self.emit(
                    type="dev_solution_accessibility",
                    severity="info",
                    msg=f"Solution [MEDIUM]: {solution.title} - "
                    f"Impact: {solution.expected_impact_pct:.0f}% | Cost: ${solution.estimated_cost_usd:,.0f}",
                    x=zone.center_x,
                    y=zone.center_y,
                    solution_id=solution.solution_id,
                    zone_id=solution.zone_id,
                    title=solution.title,
                    description=solution.description,
                    cost=solution.estimated_cost_usd,
                    expected_impact_pct=solution.expected_impact_pct,
                    implementation_steps=solution.implementation_steps,
                )
                events.append(event)

            # Safety solutions
            safety_solutions = self._generate_solution_for_safety(
                zone, self._last_business_metrics
            )
            for solution in safety_solutions:
                self._generated_solutions[solution.solution_id] = solution
                event = self.emit(
                    type="dev_solution_safety",
                    severity="warning" if solution.priority == "high" else "info",
                    msg=f"Solution [{solution.priority.upper()}]: {solution.title} - "
                    f"Impact: {solution.expected_impact_pct:.0f}% | Cost: ${solution.estimated_cost_usd:,.0f}",
                    x=zone.center_x,
                    y=zone.center_y,
                    solution_id=solution.solution_id,
                    zone_id=solution.zone_id,
                    title=solution.title,
                    description=solution.description,
                    cost=solution.estimated_cost_usd,
                    expected_impact_pct=solution.expected_impact_pct,
                    implementation_steps=solution.implementation_steps,
                )
                events.append(event)

            # Development solutions
            dev_solutions = self._generate_solution_for_development(zone)
            for solution in dev_solutions:
                self._generated_solutions[solution.solution_id] = solution
                event = self.emit(
                    type="dev_solution_development",
                    severity="warning" if zone.development_viability > 70 else "info",
                    msg=f"Solution [{solution.priority.upper()}]: {solution.title} - "
                    f"Impact: {solution.expected_impact_pct:.0f}% | Cost: ${solution.estimated_cost_usd:,.0f} | "
                    f"Timeline: {solution.estimated_timeframe_months} months",
                    x=zone.center_x,
                    y=zone.center_y,
                    solution_id=solution.solution_id,
                    zone_id=solution.zone_id,
                    title=solution.title,
                    description=solution.description,
                    recommended_use=zone.recommended_use,
                    viability=zone.development_viability,
                    cost=solution.estimated_cost_usd,
                    timeframe_months=solution.estimated_timeframe_months,
                    expected_impact_pct=solution.expected_impact_pct,
                    implementation_steps=solution.implementation_steps,
                )
                events.append(event)

        # ── Market summary (quarterly) ────────────────────────────────────
        if self._total_analysis_cycles % 4 == 0:
            market = self._calculate_market_quarter(zones, self._last_business_metrics)
            self._market_quarters.append(market)

            summary_msg = (
                f"Market Q{market.quarter_num}: {market.high_value_zones_count} high-value zones, "
                f"${market.estimated_total_opportunity_usd/1e6:.1f}M total opportunity, "
                f"Trend: {market.market_trend}"
            )
            event = self.emit(
                type="dev_market_summary",
                severity="info",
                msg=summary_msg,
                x=0.0,
                y=0.0,
                quarter_num=market.quarter_num,
                high_value_zones_count=market.high_value_zones_count,
                total_opportunity_usd=market.estimated_total_opportunity_usd,
                avg_accessibility_score=market.avg_accessibility_score,
                market_trend=market.market_trend,
                infrastructure_needs=market.infrastructure_needs,
                risk_factors=market.risk_factors,
            )
            events.append(event)

        _log(
            f"Generated {len(events)} recommendations from {len(zones)} zones "
            f"(risk_zones={len(risks)})"
        )

        return events

    # ── internal: zone detection from vehicles ────────────────────────────────

    def _create_zone_opportunities_from_vehicles(
        self,
        vehicles: list[dict],
    ) -> list[_ZoneOpportunity]:
        """
        Create zone opportunities from vehicle clusters.
        This is a simplified clustering algorithm.
        """
        if len(vehicles) < self.min_zone_vehicles:
            return []

        zones = []
        assigned = set()
        cluster_radius_cm = 15000.0  # 150 meters
        r2 = cluster_radius_cm ** 2

        for i, v1 in enumerate(vehicles):
            if i in assigned:
                continue

            x1 = float(v1.get("x", 0.0))
            y1 = float(v1.get("y", 0.0))
            speed1 = float(v1.get("speed", 0.0))

            # Find neighbors
            cluster = [v1]
            assigned.add(i)

            for j, v2 in enumerate(vehicles):
                if j in assigned:
                    continue
                x2 = float(v2.get("x", 0.0))
                y2 = float(v2.get("y", 0.0))
                dist_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
                if dist_sq <= r2:
                    cluster.append(v2)
                    assigned.add(j)

            if len(cluster) >= self.min_zone_vehicles:
                # Calculate cluster center
                cx = sum(float(v.get("x", 0.0)) for v in cluster) / len(cluster)
                cy = sum(float(v.get("y", 0.0)) for v in cluster) / len(cluster)
                avg_speed = sum(float(v.get("speed", 0.0)) for v in cluster) / len(cluster)

                # Calculate density
                area_km2 = math.pi * (cluster_radius_cm / 100000.0) ** 2
                density = len(cluster) / area_km2 if area_km2 > 0 else 0

                is_congested = avg_speed < self.congestion_threshold_cms

                zone = self._analyze_zone_opportunity(
                    zone_id=f"Z_{len(zones)}",
                    center_x=cx,
                    center_y=cy,
                    vehicle_count=len(cluster),
                    avg_speed_cms=avg_speed,
                    density_vehicles_per_sqkm=density,
                    is_congested=is_congested,
                )

                zones.append(zone)

        return zones

    # ── public methods ────────────────────────────────────────────────────────

    def set_business_metrics(self, metrics: dict) -> None:
        """
        Called by external code to provide latest business analytics.
        Typically called after AnalyticsAgent generates a report.
        """
        self._last_business_metrics = metrics

    def get_recommendations_summary(self) -> dict:
        """
        Get a human-readable summary of current recommendations.
        Useful for dashboard or report generation.
        """
        high_value_zones = [
            z for z in self._opportunities_by_zone.values()
            if z.development_viability > 70
        ]
        medium_value_zones = [
            z for z in self._opportunities_by_zone.values()
            if 50 <= z.development_viability <= 70
        ]

        total_opportunity = sum(z.estimated_real_estate_value for z in self._opportunities_by_zone.values())

        return {
            "summary": {
                "total_zones_analyzed": len(self._opportunities_by_zone),
                "high_value_opportunities": len(high_value_zones),
                "medium_value_opportunities": len(medium_value_zones),
                "total_market_opportunity_usd": total_opportunity,
                "analysis_cycles_completed": self._total_analysis_cycles,
            },
            "top_opportunities": [
                {
                    "zone_id": z.zone_id,
                    "location": (z.center_x, z.center_y),
                    "recommended_use": z.recommended_use,
                    "viability_score": z.development_viability,
                    "estimated_value": z.estimated_real_estate_value,
                }
                for z in sorted(
                    high_value_zones,
                    key=lambda z: z.development_viability,
                    reverse=True,
                )[:5]
            ],
            "identified_risks": {
                zone_id: score for zone_id, score in self._risk_zones.items()
                if score > 60
            },
            "market_history": [
                {
                    "quarter": q.quarter_num,
                    "high_value_zones": q.high_value_zones_count,
                    "opportunity_usd": q.estimated_total_opportunity_usd,
                    "trend": q.market_trend,
                }
                for q in self._market_quarters
            ],
        }

    def get_zone_development_strategy(self, zone_id: str) -> dict | None:
        """
        Get detailed development strategy for a specific zone.
        """
        zone = self._opportunities_by_zone.get(zone_id)
        if not zone:
            return None

        infra_gaps = self._detect_infrastructure_gaps([zone])
        risks = self._identify_risk_factors([zone], self._last_business_metrics)

        strategy = {
            "zone_id": zone.zone_id,
            "location": {"x": zone.center_x, "y": zone.center_y},
            "recommended_use": zone.recommended_use,
            "development_metrics": {
                "accessibility_score": zone.accessibility_score,
                "congestion_risk": zone.congestion_risk,
                "viability_score": zone.development_viability,
                "estimated_land_value": zone.estimated_real_estate_value,
            },
            "market_indicators": {
                "vehicle_count": zone.vehicle_count,
                "avg_speed_cms": zone.avg_speed_cms,
                "density_vehicles_per_sqkm": zone.density_vehicles_per_sqkm,
            },
            "infrastructure_requirements": infra_gaps.get(zone_id, {}).get("gaps", []),
            "risk_assessment": risks.get(zone_id, 0.0),
            "development_phases": self._generate_development_phases(zone),
            "expected_timeline_years": self._estimate_timeline(zone),
        }

        return strategy

    def _generate_development_phases(self, zone: _ZoneOpportunity) -> list[dict]:
        """Generate phased development strategy for a zone."""
        phases = []

        if zone.recommended_use == "commercial_retail":
            phases = [
                {
                    "phase": 1,
                    "duration_months": 12,
                    "focus": "Infrastructure prep & land acquisition",
                    "investment_pct": 20,
                },
                {
                    "phase": 2,
                    "duration_months": 18,
                    "focus": "Foundational retail spaces",
                    "investment_pct": 50,
                },
                {
                    "phase": 3,
                    "duration_months": 12,
                    "focus": "Service spaces & parking",
                    "investment_pct": 30,
                },
            ]
        elif zone.recommended_use == "mixed_use":
            phases = [
                {
                    "phase": 1,
                    "duration_months": 9,
                    "focus": "Land acquisition & planning",
                    "investment_pct": 15,
                },
                {
                    "phase": 2,
                    "duration_months": 24,
                    "focus": "Residential towers",
                    "investment_pct": 45,
                },
                {
                    "phase": 3,
                    "duration_months": 12,
                    "focus": "Commercial & retail integration",
                    "investment_pct": 25,
                },
                {
                    "phase": 4,
                    "duration_months": 6,
                    "focus": "Public spaces & final touches",
                    "investment_pct": 15,
                },
            ]
        else:
            phases = [
                {
                    "phase": 1,
                    "duration_months": 6,
                    "focus": "Feasibility & permits",
                    "investment_pct": 10,
                },
                {
                    "phase": 2,
                    "duration_months": 12,
                    "focus": "Main construction",
                    "investment_pct": 70,
                },
                {
                    "phase": 3,
                    "duration_months": 6,
                    "focus": "Testing & handover",
                    "investment_pct": 20,
                },
            ]

        return phases

    def _estimate_timeline(self, zone: _ZoneOpportunity) -> int:
        """Estimate total development timeline based on zone type."""
        if zone.recommended_use == "commercial_retail":
            return 3
        elif zone.recommended_use == "mixed_use":
            return 4
        elif zone.recommended_use == "residential_metro":
            return 3
        elif zone.recommended_use == "residential_suburban":
            return 2
        else:  # industrial
            return 2

    # ── public solution methods ───────────────────────────────────────────────

    def get_all_solutions(self) -> dict[str, dict]:
        """
        Get all generated solutions organized by type.
        Returns comprehensive action plan for developers and city planners.
        """
        solutions_by_type = {
            "congestion": [],
            "accessibility": [],
            "safety": [],
            "development": []
        }

        for solution_id, solution in self._generated_solutions.items():
            solution_dict = {
                "id": solution.solution_id,
                "zone_id": solution.zone_id,
                "title": solution.title,
                "description": solution.description,
                "priority": solution.priority,
                "cost": f"${solution.estimated_cost_usd:,.0f}",
                "timeframe": f"{solution.estimated_timeframe_months} months",
                "expected_impact": f"{solution.expected_impact_pct:.0f}%",
                "expected_benefit": solution.expected_benefit,
                "responsible_party": solution.responsible_party,
                "implementation_steps": solution.implementation_steps,
                "success_metrics": solution.success_metrics,
                "dependencies": solution.dependencies,
                "location": {"x": solution.location[0], "y": solution.location[1]},
            }
            solutions_by_type[solution.problem_type].append(solution_dict)

        return {
            "summary": {
                "total_solutions": len(self._generated_solutions),
                "by_type": {
                    key: len(val) for key, val in solutions_by_type.items()
                },
                "total_investment_required": f"${sum(s.estimated_cost_usd for s in self._generated_solutions.values()):,.0f}",
            },
            "solutions": solutions_by_type,
        }

    def get_solutions_for_zone(self, zone_id: str) -> dict | None:
        """
        Get all solutions recommended for a specific zone.
        Useful for developers planning for a particular area.
        """
        zone_solutions = [
            sol for sol in self._generated_solutions.values()
            if sol.zone_id == zone_id
        ]

        if not zone_solutions:
            return None

        return {
            "zone_id": zone_id,
            "total_solutions": len(zone_solutions),
            "total_investment": f"${sum(s.estimated_cost_usd for s in zone_solutions):,.0f}",
            "solutions": [
                {
                    "id": sol.solution_id,
                    "type": sol.problem_type,
                    "title": sol.title,
                    "priority": sol.priority,
                    "cost": f"${sol.estimated_cost_usd:,.0f}",
                    "impact": f"{sol.expected_impact_pct:.0f}%",
                    "steps": sol.implementation_steps,
                    "metrics": sol.success_metrics,
                }
                for sol in zone_solutions
            ],
        }

    def get_priority_action_plan(self) -> dict:
        """
        Get prioritized action plan - which solutions to implement first.
        Useful for city planners and project managers.
        """
        # Sort by priority (high > medium > low) and impact
        sorted_solutions = sorted(
            self._generated_solutions.values(),
            key=lambda s: (
                {"high": 0, "medium": 1, "low": 2}.get(s.priority, 2),
                -s.expected_impact_pct  # Negative for descending impact
            ),
        )

        high_priority = [s for s in sorted_solutions if s.priority == "high"]
        medium_priority = [s for s in sorted_solutions if s.priority == "medium"]
        low_priority = [s for s in sorted_solutions if s.priority == "low"]

        return {
            "urgent_action_plan": {
                "high_priority_count": len(high_priority),
                "solutions": [
                    {
                        "title": s.title,
                        "zone": s.zone_id,
                        "cost": f"${s.estimated_cost_usd:,.0f}",
                        "timeline": f"{s.estimated_timeframe_months} months",
                        "expected_benefit": s.expected_benefit,
                    }
                    for s in high_priority
                ],
                "total_investment": f"${sum(s.estimated_cost_usd for s in high_priority):,.0f}",
            },
            "planned_improvements": {
                "medium_priority_count": len(medium_priority),
                "solutions": [s.title for s in medium_priority],
                "total_investment": f"${sum(s.estimated_cost_usd for s in medium_priority):,.0f}",
            },
            "future_initiatives": {
                "low_priority_count": len(low_priority),
                "solutions": [s.title for s in low_priority],
            },
            "implementation_timeline": {
                "phase_1_0_6_months": [
                    s.title for s in sorted_solutions
                    if s.estimated_timeframe_months <= 6
                ],
                "phase_2_6_12_months": [
                    s.title for s in sorted_solutions
                    if 6 < s.estimated_timeframe_months <= 12
                ],
                "phase_3_12plus_months": [
                    s.title for s in sorted_solutions
                    if s.estimated_timeframe_months > 12
                ],
            },
        }

    def __repr__(self) -> str:
        return (
            f"<RecommendationAgent "
            f"zones_evaluated={len(self._opportunities_by_zone)} "
            f"solutions_generated={len(self._generated_solutions)} "
            f"cycles={self._total_analysis_cycles}>"
        )
