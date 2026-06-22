"""
Configuration for the SUMO-to-WebGIS simulation bridge.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SimulationConfig:
    """All tuneable simulation parameters."""

    sumo_net_file: Optional[str] = None
    usda_file: Optional[str] = None

    num_vehicles: int = 50
    min_speed_kmh: float = 30.0
    max_speed_kmh: float = 80.0
    vehicle_length: float = 4.5
    vehicle_types: list[str] = field(
        default_factory=lambda: ["sedan", "suv", "truck"]
    )

    duration_seconds: float = 300.0
    sumo_step_length: float = 0.02
    udp_send_rate_hz: float = 60.0

    udp_host: str = "127.0.0.1"
    udp_port: int = 5005

    origin_offset_x: float = -233818.0
    origin_offset_y: float = -525853.0
    origin_offset_z: float = 0.0
    scale_factor: float = 100.0

    grid_rows: int = 5
    grid_cols: int = 5
    grid_spacing: float = 200.0
    lane_count: int = 2
    speed_limit_kmh: float = 60.0

    sumo_binary: str = "sumo-gui"
    sumo_port: int = 8813

    @property
    def min_speed_ms(self) -> float:
        return self.min_speed_kmh / 3.6

    @property
    def max_speed_ms(self) -> float:
        return self.max_speed_kmh / 3.6

    @property
    def speed_limit_ms(self) -> float:
        return self.speed_limit_kmh / 3.6
