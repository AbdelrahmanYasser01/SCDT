import urllib.request
import subprocess
import sys
import os

# New Cairo Bounding Box (Central 90th Street area, ~2x2 km for faster download)
# Min Lat, Min Lon, Max Lat, Max Lon
bbox = "30.020,31.450,30.040,31.470"

print("1. Downloading OSM data for New Cairo...")
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
        with open('new_cairo.osm', 'wb') as f:
            f.write(response.read())
    print("   Downloaded new_cairo.osm successfully.")
except Exception as e:
    print(f"Error downloading OSM data: {e}")
    sys.exit(1)

print("2. Converting OSM to SUMO network...")
try:
    subprocess.run([
        "netconvert", 
        "--osm-files", "new_cairo.osm", 
        "-o", "new_cairo.net.xml", 
        "--geometry.remove", 
        "--roundabouts.guess", 
        "--ramps.guess", 
        "--junctions.join", 
        "--tls.guess-signals", 
        "--tls.discard-simple", 
        "--tls.join"
    ], check=True)
    print("   Generated new_cairo.net.xml.")
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
        "-n", "new_cairo.net.xml",
        "-o", "new_cairo.trips.xml",
        "-e", "3600",
        "-p", "1.5" # Spawn a vehicle every 1.5 seconds
    ], check=True)
    print("   Generated new_cairo.trips.xml.")
except subprocess.CalledProcessError as e:
    print(f"Error generating random trips: {e}")
    sys.exit(1)

print("4. Routing trips...")
try:
    subprocess.run([
        "duarouter",
        "-n", "new_cairo.net.xml",
        "--route-files", "new_cairo.trips.xml",
        "-o", "new_cairo.rou.xml",
        "--ignore-errors"
    ], check=True)
    print("   Generated new_cairo.rou.xml.")
except subprocess.CalledProcessError as e:
    print(f"Error routing trips: {e}")
    sys.exit(1)

print("5. Creating SUMO configuration file...")
sumocfg_content = """<configuration>
    <input>
        <net-file value="new_cairo.net.xml"/>
        <route-files value="new_cairo.rou.xml"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="3600"/>
    </time>
</configuration>"""
with open("new_cairo.sumocfg", "w") as f:
    f.write(sumocfg_content)
print("   Generated new_cairo.sumocfg.")

print("All done! New Cairo network is ready.")
