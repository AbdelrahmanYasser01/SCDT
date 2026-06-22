# """
# agents/hazard_agent.py
# ──────────────────────
# Hazard Detection Agent.
# Randomly generates hazard events at a configurable interval,
# emits a hazard_alert event for Unreal HUD, and injects an
# emergency vehicle directly into SUMO via TraCI.
# """

# from __future__ import annotations
# import random
# import uuid
# import datetime
# import traci
# from .base_agent import BaseAgent, AgentEvent

# # ── Hazard rule table ─────────────────────────────────────────────────────────

# HAZARD_RULES: dict[str, dict] = {
#     "fire":              {"severity": "critical", "responder": "firetruck"},
#     "fight":             {"severity": "warning",  "responder": "police"},
#     "medical_emergency": {"severity": "critical", "responder": "ambulance"},
#     "gas_leak":          {"severity": "critical", "responder": "firetruck"},
#     "robbery":           {"severity": "warning",  "responder": "police"},
# }

# # ── Agent ─────────────────────────────────────────────────────────────────────

# class HazardAgent(BaseAgent):

#     def __init__(
#         self,
#         interval_ticks:  int   = 300,
#         map_x_min:       float = 0.0,
#         map_x_max:       float = 100000.0,   # Unreal X = north direction
#         map_y_min:       float = 0.0,
#         map_y_max:       float = 100000.0,   # Unreal Y = east direction
#         station_x:       float = -210000.0,
#         station_y:       float = -480000.0,
#         scale_factor:    float = 100.0,      # ← new
#         origin_offset_x: float = 0.0,       # ← new
#         origin_offset_y: float = 0.0,       # ← new
#     ):
#         super().__init__(name="HazardAgent")
#         self.interval_ticks   = interval_ticks
#         self.map_x_min        = map_x_min
#         self.map_x_max        = map_x_max
#         self.map_y_min        = map_y_min
#         self.map_y_max        = map_y_max
#         self.station_x        = station_x
#         self.station_y        = station_y
#         self.scale_factor     = scale_factor
#         self.origin_offset_x  = origin_offset_x
#         self.origin_offset_y  = origin_offset_y

#         self._ticks_since_last: int = 0
#         self._active_hazards:   dict[str, dict] = {}

#     # ── main hook ─────────────────────────────────────────────────────────────

#     def process(
#         self,
#         vehicles: list[dict],
#         sim_time: float,
#         step:     int,
#     ) -> list[AgentEvent]:

#         self._ticks_since_last += 1
#         if self._ticks_since_last < self.interval_ticks:
#             return []

#         self._ticks_since_last = 0
#         return self._generate_hazard(sim_time)

#     # ── hazard generation ─────────────────────────────────────────────────────

#     def _generate_hazard(self, sim_time: float) -> list[AgentEvent]:
#         hazard_type = random.choice(list(HAZARD_RULES.keys()))
#         rule        = HAZARD_RULES[hazard_type]
#         hazard_id   = f"HZD_{uuid.uuid4().hex[:6].upper()}"

#         # x = round(random.uniform(self.map_x_min, self.map_x_max), 1)
#         # y = round(random.uniform(self.map_y_min, self.map_y_max), 1)
#         x = self.origin_offset_x + random.uniform(10000, 90000)
#         y = self.origin_offset_y + random.uniform(10000, 90000)

#         self._active_hazards[hazard_id] = {
#             "type":      hazard_type,
#             "x":         x,
#             "y":         y,
#             "responder": rule["responder"],
#         }

#         print(
#             f"[HazardAgent] ⚠ {hazard_type.upper()} at ({x:.0f}, {y:.0f}) "
#             f"→ dispatching {rule['responder']}  [{hazard_id}]"
#         )

#         # Send alert event to Unreal HUD via UDP (same as all other agents)
#         alert = self.emit(
#             type = "hazard_alert",
#             msg  = f"{hazard_type.replace('_', ' ').title()} detected",
#             severity = rule["severity"],
#             x = x, y = y,
#             hazard_id = hazard_id,
#             hazard_type = hazard_type,
#             responder_needed = rule["responder"],
#             timestamp = datetime.datetime.now().isoformat(),
#         )

#         # Inject emergency vehicle into SUMO — it routes itself on real roads
#         self._dispatch_via_sumo(hazard_id, rule["responder"], x, y)

#         return [alert]

#     # ── SUMO dispatch — THIS IS NOW CORRECTLY INSIDE THE CLASS ───────────────

#     # def _dispatch_via_sumo(
#     #     self,
#     #     hazard_id:    str,
#     #     vehicle_type: str,
#     #     dest_x:       float,
#     #     dest_y:       float,
#     # ) -> None:
#     #     vehicle_id = f"EV_{hazard_id}"
#     #     ev_type_id = f"ev_{vehicle_type}"
#     #     route_id   = f"RT_{hazard_id}" # Unique route for this dispatch
        
#     #     color_map = {
#     #         "ev_firetruck": (255, 50, 50, 255),
#     #         "ev_police":    (50, 50, 255, 255),
#     #         "ev_ambulance": (255, 255, 255, 255),
#     #     }

#     #     # 1. Coordinate Transform (Unreal -> SUMO)
#     #     sumo_dest_x = (dest_y - self.origin_offset_y) / self.scale_factor
#     #     sumo_dest_y = (dest_x - self.origin_offset_x) / self.scale_factor
#     #     sumo_sta_x  = (self.station_y - self.origin_offset_y) / self.scale_factor
#     #     sumo_sta_y  = (self.station_x - self.origin_offset_x) / self.scale_factor

#     #     try:
#     #         # 2. Find closest road edges
#     #         dest_road = traci.simulation.convertRoad(sumo_dest_x, sumo_dest_y, isGeo=False)
#     #         sta_road  = traci.simulation.convertRoad(sumo_sta_x, sumo_sta_y, isGeo=False)
#     #         dest_edge = dest_road[0]
#     #         start_edge = sta_road[0]

#     #         # 3. CALCULATE THE ROUTE FIRST
#     #         # This asks SUMO: "Find me a path from A to B"
#     #         route_info = traci.simulation.findRoute(start_edge, dest_edge)
#     #         if not route_info.edges:
#     #             print(f"[HazardAgent] ⚠ No valid path found from {start_edge} to {dest_edge}!")
#     #             return

#     #         # 4. Register the route and the vehicle type
#     #         traci.route.add(route_id, route_info.edges)
            
#     #         existing_types = traci.vehicletype.getIDList()
#     #         if ev_type_id not in existing_types:
#     #             base = existing_types[0] if existing_types else "DEFAULT_VEHTYPE"
#     #             traci.vehicletype.copy(base, ev_type_id)
#     #             traci.vehicletype.setColor(ev_type_id, color_map.get(ev_type_id, (255, 0, 0, 255)))
#     #             traci.vehicletype.setMaxSpeed(ev_type_id, 35.0) # Faster!

#     #         # 5. Spawn the vehicle with the pre-calculated route
#     #         traci.vehicle.add(
#     #             vehID       = vehicle_id,
#     #             routeID     = route_id,
#     #             typeID      = ev_type_id,
#     #             depart      = "now",
#     #             departLane  = "best",
#     #             departSpeed = "max"
#     #         )

#     #         # Emergency behavior: Override speed and ignore traffic light "caution"
#     #         traci.vehicle.setSpeedMode(vehicle_id, 7) 
#     #         traci.vehicle.setSpeed(vehicle_id, 25.0) # Constant 90km/h
            
#     #         print(f"[HazardAgent] ✓ {vehicle_type} ({vehicle_id}) following route {route_id}")

#     #     except Exception as e:
#     #         print(f"[HazardAgent] TraCI dispatch error for {vehicle_id}: {e}")


#     def _dispatch_via_sumo(
#         self,
#         hazard_id:    str,
#         vehicle_type: str,
#         dest_x:       float,
#         dest_y:       float,
#     ) -> None:
#         vehicle_id = f"EV_{hazard_id}"
#         ev_type_id = f"ev_{vehicle_type}"
#         route_id   = f"RT_{hazard_id}"
        
#         color_map = {
#             "ev_firetruck": (255, 50, 50, 255),
#             "ev_police":    (50, 50, 255, 255),
#             "ev_ambulance": (255, 255, 255, 255),
#         }

#         # 1. Coordinate Transform (Unreal -> SUMO)
#         sumo_dest_x = (dest_y - self.origin_offset_y) / self.scale_factor
#         sumo_dest_y = (dest_x - self.origin_offset_x) / self.scale_factor
#         sumo_sta_x  = (self.station_y - self.origin_offset_y) / self.scale_factor
#         sumo_sta_y  = (self.station_x - self.origin_offset_x) / self.scale_factor

#         try:
#             # 2. CREATE/VALIDATE VEHICLE TYPE FIRST
#             # We must do this BEFORE finding a route so SUMO knows the permissions
#             existing_types = traci.vehicletype.getIDList()
#             if ev_type_id not in existing_types:
#                 traci.vehicletype.copy("DEFAULT_VEHTYPE", ev_type_id)
#                 # This is the "Magic Key" - allows driving on restricted roads
#                 traci.vehicletype.setVehicleClass(ev_type_id, "emergency")
#                 traci.vehicletype.setColor(ev_type_id, color_map.get(ev_type_id, (255, 0, 0, 255)))
#                 traci.vehicletype.setMaxSpeed(ev_type_id, 35.0)

#             # 3. SNAP TO ROAD (Using Emergency Permissions)
#             dest_road = traci.simulation.convertRoad(sumo_dest_x, sumo_dest_y, isGeo=False, vClass="emergency")
#             sta_road  = traci.simulation.convertRoad(sumo_sta_x, sumo_sta_y, isGeo=False, vClass="emergency")
#             dest_edge = dest_road[0]
#             start_edge = sta_road[0]

#             # 4. INTERSECTION NUDGE
#             # If we are inside a junction (edge starts with ':'), nudge the start point
#             if start_edge.startswith(":"):
#                 sta_road = traci.simulation.convertRoad(sumo_sta_x + 10.0, sumo_sta_y + 10.0, isGeo=False, vClass="emergency")
#                 start_edge = sta_road[0]

#             # 5. FIND ROUTE (Passing the specific vType)
#             # This tells SUMO: "Find a path specifically for an Emergency Vehicle"
#             route_info = traci.simulation.findRoute(start_edge, dest_edge, vType=ev_type_id)
            
#             if not route_info.edges:
#                 print(f"[HazardAgent] ⚠ No path found for {ev_type_id} from {start_edge} to {dest_edge}")
#                 return

#             # 6. SPAWN
#             traci.route.add(route_id, route_info.edges)
#             traci.vehicle.add(
#                 vehID=vehicle_id,
#                 routeID=route_id,
#                 typeID=ev_type_id,
#                 depart="now",
#                 departLane="best",
#                 departSpeed="max"
#             )

#             # Ignore traffic lights and speed limits (Emergency Mode)
#             traci.vehicle.setSpeedMode(vehicle_id, 7) 
            
#             print(f"[HazardAgent] ✓ {vehicle_type} dispatched successfully!")

#         except Exception as e:
#             print(f"[HazardAgent] TraCI dispatch error for {vehicle_id}: {e}")
#     # ── helpers ───────────────────────────────────────────────────────────────

#     def resolve_hazard(self, hazard_id: str) -> None:
#         if hazard_id in self._active_hazards:
#             del self._active_hazards[hazard_id]
#             print(f"[HazardAgent] Hazard {hazard_id} resolved.")

#     def active_hazard_count(self) -> int:
#         return len(self._active_hazards)

#     def on_stop(self) -> None:
#         if self._active_hazards:
#             print(f"[HazardAgent] {len(self._active_hazards)} unresolved hazards at shutdown.")
#         super().on_stop()


"""
agents/hazard_agent.py
──────────────────────
Hazard Detection Agent.
Randomly generates hazard events at a configurable interval,
emits a hazard_alert event for Unreal HUD, and injects an
emergency vehicle directly into SUMO via TraCI.
"""

from __future__ import annotations
import random
import uuid
import datetime
import traci
from .base_agent import BaseAgent, AgentEvent

HAZARD_RULES: dict[str, dict] = {
    "fire":              {"severity": "critical", "responder": "firetruck"},
    "fight":             {"severity": "warning",  "responder": "police"},
    "medical_emergency": {"severity": "critical", "responder": "ambulance"},
    "gas_leak":          {"severity": "critical", "responder": "firetruck"},
    "robbery":           {"severity": "warning",  "responder": "police"},
}

COLOR_MAP = {
    "ev_firetruck": (255, 50,  50,  255),
    "ev_police":    (50,  50,  255, 255),
    "ev_ambulance": (255, 255, 255, 255),
}


class HazardAgent(BaseAgent):

    def __init__(
        self,
        interval_ticks:  int   = 1000,
        scale_factor:    float = 100.0,
        origin_offset_x: float = 0.0,
        origin_offset_y: float = 0.0,
        # station_x/y kept as params but no longer used for routing
        station_x:       float = 0.0,
        station_y:       float = 0.0,
    ):
        super().__init__(name="HazardAgent")
        self.interval_ticks   = interval_ticks
        self.scale_factor     = scale_factor
        self.origin_offset_x  = origin_offset_x
        self.origin_offset_y  = origin_offset_y

        self._ticks_since_last: int       = 0
        self._active_hazards:   dict      = {}
        self._valid_edges:      list[str] = []  # cached on first use

    # ── main hook ─────────────────────────────────────────────────

    def process(
        self,
        vehicles: list[dict],
        sim_time: float,
        step:     int,
        *,
        context     = None,    # AgentContext — available for zone/hazard state
        prev_events = None,    # list[AgentEvent] from previous tick
    ) -> list[AgentEvent]:
        self._ticks_since_last += 1
        if self._ticks_since_last < self.interval_ticks:
            return []
        self._ticks_since_last = 0
        return self._generate_hazard(sim_time)

    # ── hazard generation ─────────────────────────────────────────

    # def _generate_hazard(self, sim_time: float) -> list[AgentEvent]:
    #     hazard_type = random.choice(list(HAZARD_RULES.keys()))
    #     rule        = HAZARD_RULES[hazard_type]
    #     hazard_id   = f"HZD_{uuid.uuid4().hex[:6].upper()}"

    #     # Generate random Unreal coordinates within the mapped area
    #     x = self.origin_offset_x + random.uniform(20000, 80000)
    #     y = self.origin_offset_y + random.uniform(20000, 80000)

    #     self._active_hazards[hazard_id] = {
    #         "type": hazard_type, "x": x, "y": y,
    #         "responder": rule["responder"],
    #     }

    #     print(
    #         f"[HazardAgent] ⚠ {hazard_type.upper()} at "
    #         f"({x:.0f}, {y:.0f}) → dispatching {rule['responder']} [{hazard_id}]"
    #     )

    #     alert = self.emit(
    #         type             = "hazard_alert",
    #         msg              = f"{hazard_type.replace('_', ' ').title()} — {rule['responder']} dispatched",
    #         severity         = rule["severity"],
    #         x                = x,
    #         y                = y,
    #         hazard_id        = hazard_id,
    #         hazard_type      = hazard_type,
    #         responder_needed = rule["responder"],
    #         timestamp        = datetime.datetime.now().isoformat(),
    #     )

    #     self._dispatch_via_sumo(hazard_id, rule["responder"], x, y)
    #     return [alert]

    # # ── SUMO dispatch ─────────────────────────────────────────────

    # def _dispatch_via_sumo(
    #     self,
    #     hazard_id:    str,
    #     vehicle_type: str,
    #     dest_x:       float,
    #     dest_y:       float,
    # ) -> None:

    #     vehicle_id = f"EV_{hazard_id}"
    #     ev_type_id = f"ev_{vehicle_type}"
    #     route_id   = f"RT_{hazard_id}"

    #     # Unreal cm → SUMO meters (reverse axis swap)
    #     sumo_dest_x = (dest_y - self.origin_offset_y) / self.scale_factor
    #     sumo_dest_y = (dest_x - self.origin_offset_x) / self.scale_factor

    #     try:
    #         # ── 1. Ensure vehicle type exists ─────────────────────
    #         self._ensure_vtype(ev_type_id)

    #         # ── 2. Find destination edge ──────────────────────────
    #         dest_edge = self._snap_to_edge(sumo_dest_x, sumo_dest_y)
    #         if dest_edge is None:
    #             print(f"[HazardAgent] Could not snap destination to any edge, skipping {vehicle_id}.")
    #             return

    #         # ── 3. Find a start edge with a valid route ───────────
    #         start_edge, route_edges = self._find_route_to(dest_edge, ev_type_id)
    #         if not route_edges:
    #             print(f"[HazardAgent] No valid route found to {dest_edge}, skipping {vehicle_id}.")
    #             return

    #         # ── 4. Register route ─────────────────────────────────
    #         traci.route.add(route_id, route_edges)

    #         # ── 5. Add vehicle ────────────────────────────────────
    #         traci.vehicle.add(
    #             vehID       = vehicle_id,
    #             routeID     = route_id,
    #             typeID      = ev_type_id,
    #             depart      = "now",
    #             departLane  = "best",
    #             departSpeed = "0",
    #         )

    #         # ── 6. Emergency speed override ───────────────────────
    #         traci.vehicle.setSpeedMode(vehicle_id, 7)   # ignore all limits
    #         traci.vehicle.setSpeed(vehicle_id, 25.0)    # 25 m/s = 90 km/h

    #         print(
    #             f"[HazardAgent] ✓ {vehicle_type} ({vehicle_id}) dispatched: "
    #             f"{start_edge} → {dest_edge} ({len(route_edges)} edges)"
    #         )

    #     except traci.TraCIException as e:
    #         print(f"[HazardAgent] TraCI error for {vehicle_id}: {e}")
    #     except Exception as e:
    #         print(f"[HazardAgent] Unexpected error for {vehicle_id}: {e}")
    def _generate_hazard(self, sim_time: float) -> list[AgentEvent]:
        hazard_type = random.choice(list(HAZARD_RULES.keys()))
        rule        = HAZARD_RULES[hazard_type]
        hazard_id   = f"HZD_{uuid.uuid4().hex[:6].upper()}"

    # Pick a random VALID edge as the destination — guaranteed drivable
        valid_edges = self._get_valid_edges()
        if not valid_edges:
            print(f"[HazardAgent] No valid edges in network, cannot dispatch.")
            return []

        dest_edge = random.choice(valid_edges)

    # Get the actual SUMO position of that edge for display
        try:
            edge_x, edge_y = traci.simulation.convert2D(dest_edge, 0.0)
        except Exception:
            edge_x, edge_y = 0.0, 0.0

    # Convert SUMO meters → Unreal cm for the alert display
    # Unreal X = SUMO_y * scale + offset_x
    # Unreal Y = SUMO_x * scale + offset_y
        ue_x = edge_y * self.scale_factor + self.origin_offset_x
        ue_y = edge_x * self.scale_factor + self.origin_offset_y

        self._active_hazards[hazard_id] = {
        "type": hazard_type, "x": ue_x, "y": ue_y,
        "responder": rule["responder"], "dest_edge": dest_edge,
    }

        print(
        f"[HazardAgent] ⚠ {hazard_type.upper()} at edge {dest_edge} "
        f"UE=({ue_x:.0f}, {ue_y:.0f}) → dispatching {rule['responder']} [{hazard_id}]"
    )

        alert = self.emit(
            type             = "hazard_alert",
            msg              = f"{hazard_type.replace('_', ' ').title()} — {rule['responder']} dispatched",
            severity         = rule["severity"],
            x                = ue_x,
            y                = ue_y,
            hazard_id        = hazard_id,
            hazard_type      = hazard_type,
            responder_needed = rule["responder"],
            timestamp        = datetime.datetime.now().isoformat(),
    )

        self._dispatch_via_sumo(hazard_id, rule["responder"], dest_edge)
        return [alert]


    def _dispatch_via_sumo(
        self,
        hazard_id:    str,
        vehicle_type: str,
        dest_edge:    str,          # now receives edge directly, no coordinates
    ) -> None:

        vehicle_id = f"EV_{hazard_id}"
        ev_type_id = f"ev_{vehicle_type}"
        route_id   = f"RT_{hazard_id}"

        try:
        # ── 1. Ensure vehicle type exists ─────────────────────────
            self._ensure_vtype(ev_type_id)

        # ── 2. Find a start edge with a valid route ────────────────
            start_edge, route_edges = self._find_route_to(dest_edge, ev_type_id)
            if not route_edges:
                print(f"[HazardAgent] No valid route found to {dest_edge}, skipping {vehicle_id}.")
                return

        # ── 3. Register route and add vehicle ──────────────────────
            traci.route.add(route_id, route_edges)
            traci.vehicle.add(
                vehID       = vehicle_id,
                routeID     = route_id,
                typeID      = ev_type_id,
                depart      = "now",
                departLane  = "best",
                departSpeed = "0",
            )

        # ── 4. Emergency speed override ────────────────────────────
            traci.vehicle.setSpeedMode(vehicle_id, 7)
            traci.vehicle.setSpeed(vehicle_id, 25.0)

            print(
            f"[HazardAgent] ✓ {vehicle_type} ({vehicle_id}) dispatched: "
            f"{start_edge} → {dest_edge} ({len(route_edges)} edges)"
        )

        except traci.TraCIException as e:
            print(f"[HazardAgent] TraCI error for {vehicle_id}: {e}")
        except Exception as e:
            print(f"[HazardAgent] Unexpected error for {vehicle_id}: {e}")
    # ── helpers ───────────────────────────────────────────────────

    def _ensure_vtype(self, ev_type_id: str) -> None:
        """
        Creates the emergency vehicle type if it doesn't exist yet.
        Uses 'passenger' class — allowed on all normal road edges.
        Never uses 'emergency' or 'authority' which are restricted.
        """
        if ev_type_id in traci.vehicletype.getIDList():
            return

        existing = traci.vehicletype.getIDList()
        # Prefer DEFAULT_VEHTYPE, fall back to whatever exists
        base = "DEFAULT_VEHTYPE" if "DEFAULT_VEHTYPE" in existing else existing[0]
        traci.vehicletype.copy(base, ev_type_id)
        traci.vehicletype.setVehicleClass(ev_type_id, "passenger")
        traci.vehicletype.setColor(ev_type_id, COLOR_MAP.get(ev_type_id, (255, 165, 0, 255)))
        traci.vehicletype.setMaxSpeed(ev_type_id, 40.0)
        print(f"[HazardAgent] Registered vehicle type: {ev_type_id} (class=passenger)")

    def _snap_to_edge(self, sx: float, sy: float) -> str | None:
        """
    Finds the nearest drivable passenger-accessible edge.
    Tries nudges and validates lane permissions before accepting.
    """
        nudges = [
        (0, 0), (20, 0), (0, 20), (-20, 0), (0, -20),
        (20, 20), (-20, 20), (20, -20), (-20, -20),
        (50, 0), (0, 50), (-50, 0), (0, -50),
        ]
        for dx, dy in nudges:
            try:
                edge = traci.simulation.convertRoad(
                sx + dx, sy + dy, isGeo=False
            )[0]

            # Skip junction internal edges
                if not edge or edge.startswith(":"):
                    continue

            # Validate that at least one lane accepts passenger vehicles
                if self._edge_allows_passenger(edge):
                    return edge

            except Exception:
                continue
        return None


    def _edge_allows_passenger(self, edge_id: str) -> bool:
        """
    Returns True if the edge has at least one lane that
    allows passenger vehicles (or has no restriction at all).
    """
        try:
            num_lanes = traci.edge.getLaneNumber(edge_id)
            for i in range(num_lanes):
                lane_id = f"{edge_id}_{i}"
                allowed = traci.lane.getAllowed(lane_id)
            # Empty list = no restriction = all vehicles allowed
                if not allowed or "passenger" in allowed:
                    return True
        except Exception:
            pass
        return False

    def _get_valid_edges(self) -> list[str]:
        """
        Returns a cached list of all drivable non-junction edges.
        Built once on first call, reused on every subsequent call.
        """
        if not self._valid_edges:
            self._valid_edges = [
                e for e in traci.edge.getIDList()
                if not e.startswith(":")
                and traci.edge.getLaneNumber(e) > 0
                and self._edge_allows_passenger(e)
            ]
            print(f"[HazardAgent] Cached {len(self._valid_edges)} valid passenger edges.")
        return self._valid_edges

    def _find_route_to(
        self,
        dest_edge:  str,
        vtype_id:   str,
        max_tries:  int = 15,
    ) -> tuple[str | None, list[str]]:
        """
        Tries to find a valid route to dest_edge.
        Priority: edges from active traffic vehicles (fastest, most reliable).
        Fallback: random drivable edges from the network.
        Returns (start_edge, route_edges) or (None, []) if nothing found.
        """
        # Build candidate list: active vehicle edges first, then random network edges
        active_edges = [
            traci.vehicle.getRoadID(vid)
            for vid in traci.vehicle.getIDList()
            if not vid.startswith("EV_")
            and not traci.vehicle.getRoadID(vid).startswith(":")
        ]

        all_valid  = self._get_valid_edges()
        random_edges = random.sample(all_valid, min(max_tries, len(all_valid)))
        candidates = list(dict.fromkeys(active_edges + random_edges))  # dedup, preserve order

        for start_edge in candidates[:max_tries]:
            if start_edge == dest_edge or not start_edge:
                continue
            try:
                result = traci.simulation.findRoute(
                    start_edge, dest_edge, vType=vtype_id
                )
                if result.edges:
                    return start_edge, list(result.edges)
            except Exception:
                continue

        return None, []

    # ── lifecycle ─────────────────────────────────────────────────

    def resolve_hazard(self, hazard_id: str) -> None:
        if hazard_id in self._active_hazards:
            del self._active_hazards[hazard_id]
            print(f"[HazardAgent] Hazard {hazard_id} resolved.")

    def active_hazard_count(self) -> int:
        return len(self._active_hazards)

    def on_stop(self) -> None:
        if self._active_hazards:
            print(f"[HazardAgent] {len(self._active_hazards)} unresolved hazards at shutdown.")
        super().on_stop()