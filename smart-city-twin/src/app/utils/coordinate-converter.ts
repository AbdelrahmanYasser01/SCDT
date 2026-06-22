export class CoordinateConverter {
  private static readonly ANCHOR_LAT = 30.0444; // Cairo Latitude
  private static readonly ANCHOR_LON = 31.2357; // Cairo Longitude
  private static readonly EARTH_RADIUS = 6378137; // Earth radius in meters

  /**
   * Converts local simulation X/Y (in meters) to global WGS84 Longitude/Latitude
   */
  static sumoToDegrees(x: number, y: number): { lon: number, lat: number } {
    // 1 degree of latitude is approximately 111,320 meters
    const latOffset = y / 111320;
    
    // 1 degree of longitude depends on the latitude
    const lonOffset = x / (111320 * Math.cos(this.ANCHOR_LAT * Math.PI / 180));

    return {
      lon: this.ANCHOR_LON + lonOffset,
      lat: this.ANCHOR_LAT + latOffset
    };
  }
}
