import os
import sys
from pathlib import Path
import traci

SUMO_CONFIG_PATH = r"c:\Users\HP\.gemini\antigravity\scratch\SmartCityDigitalTwin\Sumo_Aligned_Scripts\sumo_files\simulation.sumocfg"

sumo_dir = Path(SUMO_CONFIG_PATH).parent
os.chdir(sumo_dir)

traci.start(["sumo", "-c", SUMO_CONFIG_PATH])

boundary = traci.simulation.getNetBoundary()
print(f"Network Boundary (SUMO x,y): {boundary}")

try:
    center_x = (boundary[0][0] + boundary[1][0]) / 2
    center_y = (boundary[0][1] + boundary[1][1]) / 2
    lon, lat = traci.simulation.convertGeo(center_x, center_y)
    print(f"Center Geo (Lon, Lat): {lon}, {lat}")
except Exception as e:
    print(f"Geo conversion error: {e}")

traci.close()
