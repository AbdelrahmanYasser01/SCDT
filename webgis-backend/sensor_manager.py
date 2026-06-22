"""
sensor_manager.py
─────────────────
Sensor Math & Visibility Logic.
Vectorized computation of distance and FOV for physical sensor simulation.
"""

import json
import math
from pathlib import Path
from enum import IntEnum
from typing import Dict, List, Any

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class ESensorAlertState(IntEnum):
    NORMAL = 0
    WARNING = 1
    CONGESTION = 2
    INCIDENT = 3
    OFFLINE = 4


class SensorManager:
    def __init__(self, config_path: str = "config/sensor_layout.json"):
        self.config_path = Path(__file__).parent / config_path
        self.sensors: list[dict] = []
        self._load_config()

    def _load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.sensors = data.get("sensors", [])
        except Exception as e:
            print(f"[SensorManager] Failed to load config: {e}")
            self.sensors = []

    def _normalize_angle_deg(self, angle: float) -> float:
        angle = angle % 360.0
        if angle > 180.0:
            angle -= 360.0
        return angle

    def tick(self, vehicles: List[Dict[str, Any]], sim_time: float, step: int) -> Dict[str, List[Dict[str, Any]]]:
        localized_perception: Dict[str, List[Dict[str, Any]]] = {s["id"]: [] for s in self.sensors}

        if not vehicles or not self.sensors:
            return localized_perception

        if HAS_NUMPY:
            return self._tick_numpy(vehicles, localized_perception)
        else:
            return self._tick_python(vehicles, localized_perception)

    def _tick_numpy(self, vehicles, localized_perception):
        v_coords = np.array([[v.get("x", 0.0), v.get("y", 0.0)] for v in vehicles])

        for s in self.sensors:
            s_id = s["id"]
            sx, sy = s.get("x", 0.0), s.get("y", 0.0)
            range_cm = s.get("range_cm", 5000.0)
            fov_deg = s.get("fov_deg", 90.0)
            heading_deg = s.get("heading_deg", 0.0)
            optimal_density = s.get("optimal_density", 5)

            dx = v_coords[:, 0] - sx
            dy = v_coords[:, 1] - sy
            dist_sq = dx**2 + dy**2

            radius_mask = dist_sq <= range_cm**2
            candidate_indices = np.where(radius_mask)[0]

            if len(candidate_indices) == 0:
                continue

            c_dx = dx[candidate_indices]
            c_dy = dy[candidate_indices]
            c_dist = np.sqrt(dist_sq[candidate_indices])

            angles_rad = np.arctan2(c_dy, c_dx)
            angles_deg = np.degrees(angles_rad)

            angle_diffs = np.abs((angles_deg - heading_deg + 180.0) % 360.0 - 180.0)

            half_fov = fov_deg / 2.0
            fov_mask = angle_diffs <= half_fov

            visible_indices = candidate_indices[fov_mask]
            visible_angle_diffs = angle_diffs[fov_mask]
            visible_distances = c_dist[fov_mask]

            visible_count = len(visible_indices)
            density_degradation = 0.05 * max(0, visible_count - optimal_density)

            for idx, angle_diff, dist in zip(visible_indices, visible_angle_diffs, visible_distances):
                v_copy = vehicles[idx].copy()
                conf = 0.98
                if angle_diff >= half_fov * 0.9:
                    conf -= 0.10
                dist_penalty = 0.10 * (dist / range_cm)
                conf -= dist_penalty
                conf -= density_degradation
                v_copy["confidence"] = max(0.0, min(1.0, conf))
                localized_perception[s_id].append(v_copy)

        return localized_perception

    def _tick_python(self, vehicles, localized_perception):
        for s in self.sensors:
            s_id = s["id"]
            sx, sy = s.get("x", 0.0), s.get("y", 0.0)
            range_cm_sq = s.get("range_cm", 5000.0) ** 2
            range_cm = s.get("range_cm", 5000.0)
            fov_deg = s.get("fov_deg", 90.0)
            heading_deg = s.get("heading_deg", 0.0)
            optimal_density = s.get("optimal_density", 5)

            visible_vehicles = []
            half_fov = fov_deg / 2.0

            for v in vehicles:
                vx, vy = v.get("x", 0.0), v.get("y", 0.0)
                dx, dy = vx - sx, vy - sy
                dist_sq = dx**2 + dy**2

                if dist_sq > range_cm_sq:
                    continue

                angle_rad = math.atan2(dy, dx)
                angle_deg = math.degrees(angle_rad)
                angle_diff = abs(self._normalize_angle_deg(angle_deg - heading_deg))

                if angle_diff <= half_fov:
                    dist = math.sqrt(dist_sq)
                    visible_vehicles.append((v, angle_diff, dist))

            visible_count = len(visible_vehicles)
            density_degradation = 0.05 * max(0, visible_count - optimal_density)

            for v, angle_diff, dist in visible_vehicles:
                v_copy = v.copy()
                conf = 0.98
                if angle_diff >= half_fov * 0.9:
                    conf -= 0.10
                dist_penalty = 0.10 * (dist / range_cm)
                conf -= dist_penalty
                conf -= density_degradation
                v_copy["confidence"] = max(0.0, min(1.0, conf))
                localized_perception[s_id].append(v_copy)

        return localized_perception

    def compute_alert_code(self, visible_count: int, optimal_density: int) -> int:
        if optimal_density <= 0:
            return 0
        occ_ratio = visible_count / optimal_density
        if occ_ratio < 0.5:
            return int(ESensorAlertState.NORMAL)
        elif occ_ratio < 0.8:
            return int(ESensorAlertState.WARNING)
        else:
            return int(ESensorAlertState.CONGESTION)

    def get_sensor_status(self, sensor_data: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        result = []
        for s in self.sensors:
            sid = s["id"]
            visible = sensor_data.get(sid, [])
            count = len(visible)
            optimal = s.get("optimal_density", 5)

            occ = min(1.0, count / max(optimal, 1))
            alert_code = self.compute_alert_code(count, optimal)
            avg_conf = (
                sum(v.get("confidence", 1.0) for v in visible) / count
                if count > 0 else 1.0
            )

            result.append({
                "id":         sid,
                "type":       s.get("type", "camera"),
                "occ":        round(occ, 2),
                "alert_code": alert_code,
                "confidence": round(avg_conf, 2),
            })
        return result
