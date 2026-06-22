import urllib.request
import subprocess
import sys
import os

# Linz Bounding Box (Central area, ~2x2 km for fast download)
# Min Lat, Min Lon, Max Lat, Max Lon
bbox = "48.287,14.296,48.307,14.316"

print("1. Downloading OSM data for Linz...")
query = f"""
[out:xml][timeout:180];
(
  way["highway"]({bbox});
  node(w);
);
out body;
"""
url = "https://lz4.overpass-api.de/api/interpreter"
req = urllib.request.Request(url, data=query.encode('utf-8'), headers={'User-Agent': 'SmartCityDigitalTwin/1.0 (Python urllib)'})
try:
    with urllib.request.urlopen(req, timeout=190) as response:
        with open('linz.osm', 'wb') as f:
            f.write(response.read())
    print("   Downloaded linz.osm successfully.")
except Exception as e:
    print(f"Error downloading OSM data: {e}")
    sys.exit(1)

print("2. Converting OSM to SUMO network...")
try:
    subprocess.run([
        "netconvert", 
        "--osm-files", "linz.osm", 
        "-o", "linz.net.xml", 
        "--geometry.remove", 
        "--roundabouts.guess", 
        "--ramps.guess", 
        "--junctions.join", 
        "--tls.guess-signals", 
        "--tls.discard-simple", 
        "--tls.join"
    ], check=True)
    print("   Generated linz.net.xml.")
except subprocess.CalledProcessError as e:
    print(f"Error running netconvert: {e}")
    sys.exit(1)

print("3. Generating random trips...")
sumo_home = os.environ.get("SUMO_HOME", "")
if not sumo_home:
    print("SUMO_HOME environment variable not set. Please set it to your SUMO installation directory.")
    sys.exit(1)

randomTrips_path = os.path.join(sumo_home, "tools", "randomTrips.py")
try:
    subprocess.run([
        sys.executable, randomTrips_path,
        "-n", "linz.net.xml",
        "-o", "linz.trips.xml",
        "-e", "3600",
        "-p", "1.5" # Spawn a vehicle every 1.5 seconds
    ], check=True)
    print("   Generated linz.trips.xml.")
except subprocess.CalledProcessError as e:
    print(f"Error generating random trips: {e}")
    sys.exit(1)

print("4. Routing trips...")
try:
    subprocess.run([
        "duarouter",
        "-n", "linz.net.xml",
        "--route-files", "linz.trips.xml",
        "-o", "linz.rou.xml",
        "--ignore-errors"
    ], check=True)
    print("   Generated linz.rou.xml.")
except subprocess.CalledProcessError as e:
    print(f"Error routing trips: {e}")
    sys.exit(1)

print("5. Creating SUMO configuration file...")
sumocfg_content = """<configuration>
    <input>
        <net-file value="linz.net.xml"/>
        <route-files value="linz.rou.xml"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="3600"/>
    </time>
</configuration>"""
with open("linz.sumocfg", "w") as f:
    f.write(sumocfg_content)
print("   Generated linz.sumocfg.")

print("All done! Linz network is ready.")
