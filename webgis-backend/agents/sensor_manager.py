import json
import logging
import math
from pathlib import Path
import numpy as np

log = logging.getLogger(__name__)

class SensorManager:
    def __init__(self, config_path: str):
        self.sensors = []
        try:
            p = Path(config_path)
            if p.exists():
                with open(p, "r") as f:
                    self.sensors = json.load(f)
                log.info(f"[SensorManager] Loaded {len(self.sensors)} sensors from {config_path}")
            else:
                log.warning(f"[SensorManager] Config {config_path} not found.")
        except Exception as e:
            log.warning(f"[SensorManager] Error loading {config_path}: {e}")

    def tick(self, vehicles: list[dict], sim_time: float, step: int) -> list[dict]:
        """
        Process localized perception for all sensors using O(1) vectorized numpy math.
        Returns a list of sensor payloads to append to the UDP stream.
        """
        if not self.sensors or not vehicles:
            return []

        # Vectorize vehicles
        num_v = len(vehicles)
        v_coords = np.zeros((num_v, 2))
        for i, v in enumerate(vehicles):
            v_coords[i, 0] = v["x"]
            v_coords[i, 1] = v["y"]

        sensor_results = []

        for sensor in self.sensors:
            sx, sy = sensor.get("x", 0), sensor.get("y", 0)
            radius = sensor.get("radius_cm", 10000.0)
            
            # O(1) Distance-Squared Culling
            dx = v_coords[:, 0] - sx
            dy = v_coords[:, 1] - sy
            dist_sq = dx**2 + dy**2
            in_radius_mask = dist_sq < (radius**2)
            
            survivors = np.where(in_radius_mask)[0]
            if len(survivors) == 0:
                sensor_results.append({
                    "id": sensor["id"],
                    "type": sensor.get("type", "camera"),
                    "occ": 0.0,
                    "alert_code": 0,
                    "confidence": 1.0
                })
                continue

            # Frustum Check (if camera)
            detected_count = 0
            edge_count = 0
            
            if sensor.get("type") == "camera":
                yaw_rad = math.radians(sensor.get("yaw_deg", 0))
                fov_rad = math.radians(sensor.get("fov_deg", 90))
                half_fov = fov_rad / 2.0
                
                # Only check survivors
                angles = np.arctan2(dy[survivors], dx[survivors])
                # Normalize angles relative to camera yaw
                angle_diff = (angles - yaw_rad + np.pi) % (2 * np.pi) - np.pi
                
                # In frustum
                in_frustum = np.abs(angle_diff) <= half_fov
                
                detected_count = np.sum(in_frustum)
                edge_count = np.sum((np.abs(angle_diff) > half_fov * 0.8) & in_frustum)
            else:
                detected_count = len(survivors)

            # Confidence modeling
            confidence = 0.98
            opt_density = sensor.get("optimal_density", 5)
            if detected_count > opt_density:
                confidence -= 0.05 * (detected_count - opt_density)
            if edge_count > 0:
                confidence -= 0.10 * edge_count
                
            confidence = max(0.0, min(1.0, confidence))
            
            # alert code logic based on occupancy / density
            occ = min(1.0, detected_count / (opt_density * 2)) if opt_density else 0.0
            alert_code = 0
            if occ > 0.8:
                alert_code = 2 # Congestion
            elif occ > 0.5:
                alert_code = 1 # Warning
                
            sensor_results.append({
                "id": sensor["id"],
                "type": sensor.get("type", "camera"),
                "occ": round(occ, 2),
                "alert_code": alert_code,
                "confidence": round(float(confidence), 2)
            })

        return sensor_results
