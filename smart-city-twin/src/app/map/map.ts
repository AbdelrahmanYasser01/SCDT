import { Component, AfterViewInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { SocketService } from '../services/socket';
import { CoordinateConverter } from '../utils/coordinate-converter';

declare var Cesium: any;

@Component({
  selector: 'app-map',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './map.html',
  styleUrl: './map.css'
})
export class MapComponent implements AfterViewInit, OnDestroy {
  public lonOffset: number = 0.00000;
  public latOffset: number = 0.00000;
  public zOffset: number = 266; // Linz approximate elevation

  private viewer: any;
  private isInitialized = false;
  private entitiesRegistry = new Map<string, any>();
  private lastUpdateRegistry = new Map<string, number>();
  private cleanupInterval: any;

  constructor(private socketService: SocketService) { }

  ngAfterViewInit(): void {
    this.viewer = new Cesium.Viewer('cesiumContainer', {
      terrain: Cesium.Terrain.fromWorldTerrain(),
      infoBox: false,
      selectionIndicator: false
    });
    this.viewer.scene.globe.depthTestAgainstTerrain = false;

    // TASK-019: Integrate ArcGIS 3D Scene Layer (I3S) - Linz Mesh
    const i3sUrl = "https://tiles.arcgis.com/tiles/z2tnIkrLQ2BRzr6P/arcgis/rest/services/Linz_IM/SceneServer/layers/0";
    Cesium.I3SDataProvider.fromUrl(i3sUrl).then((i3sProvider: any) => {
      this.viewer.scene.primitives.add(i3sProvider);
      console.log("[Layer 2 - Mesh] Successfully loaded Linz I3S scene layer.");
    }).catch((err: any) => {
      console.error("[Layer 2 - Mesh] Failed to load I3S scene layer:", err);
    });

    // Start cleanup interval (remove entities not updated in 5 seconds)
    this.cleanupInterval = setInterval(() => this.cleanupStaleEntities(), 5000);

    this.socketService.onMessage((data: any) => {
      console.log(data);
      this.handleTelemetry(data);
    });
  }

  ngOnDestroy(): void {
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
    }
  }

  private handleTelemetry(data: any): void {
    console.log(`[Layer 1 - Ingestion] Payload: id=${data.id}, lon=${data.lon}, lat=${data.lat}`);
    if (typeof data.lon !== 'number' || typeof data.lat !== 'number' || Number.isNaN(data.lon)) { console.error(`[Layer 1 - FATAL] Invalid geometry payload. Check backend emission format.`); return; }
    if (!this.viewer) return;

    // Apply manual calibration offsets to resolve mesh/OSM geographic misalignment
    const degrees = { lon: data.lon + Number(this.lonOffset), lat: data.lat + Number(this.latOffset) };

    // TASK-011: Project to ECEF (Cartesian3)
    const position = Cesium.Cartesian3.fromDegrees(degrees.lon, degrees.lat, (data.z || 0) + Number(this.zOffset));
    console.log(`[Layer 2 - Projection] Cartesian3 Output:`, position);

    // [PATCHED] TASK-012 & TASK-013 & TASK-014: Automated Camera Targeting
    if (!this.isInitialized) {
      this.isInitialized = true;

      // 1. Strict Geographic Bounds Check
      if (Math.abs(degrees.lat) > 90 || Math.abs(degrees.lon) > 180) {
        console.error(`[Layer 4 - FATAL] Out of bounds geographic coordinates! Lat: ${degrees.lat}, Lon: ${degrees.lon}. The CoordinateConverter is outputting invalid geographic data (likely missing meter-to-degree conversion). Camera flight aborted to prevent WebGL crash.`);
        return;
      }

      console.log(`[Layer 4 - Camera] Executing FlyTo -> Target: Lon=${degrees.lon}, Lat=${degrees.lat}`);

      try {
        const targetPosition = Cesium.Cartesian3.fromDegrees(degrees.lon, degrees.lat, 0);
        const targetSphere = new Cesium.BoundingSphere(targetPosition, 0);

        // 2. Safe execution wrapped in a timeout to ensure Viewer DOM is fully mounted
        setTimeout(() => {
          this.viewer.camera.flyToBoundingSphere(targetSphere, {
            offset: new Cesium.HeadingPitchRange(
              Cesium.Math.toRadians(0.0),
              Cesium.Math.toRadians(-45.0),
              4000
            ),
            duration: 3.0
          });
        }, 500); // 500ms buffer 

      } catch (error) {
        console.error(`[Layer 4 - CRASH DUMP] Camera flyTo failed!`, error);
      }
    }

    // TASK-015: Lifecycle Management of Dynamic Entities
    const now = Date.now();
    this.lastUpdateRegistry.set(data.id, now);
    const time = Cesium.JulianDate.now();

    // Convert SUMO yaw_deg (0=North, 90=East) to Cesium HeadingPitchRoll
    // Subtracting 90 degrees because the 3D model defaults to facing East (+X axis).
    const heading = Cesium.Math.toRadians((data.yaw_deg || 0) - 90);
    const hpr = new Cesium.HeadingPitchRoll(heading, 0, 0);
    const orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);

    if (!this.entitiesRegistry.has(data.id)) {
      // TASK-016: Conditional Instantiation (New)
      console.log(`[Layer 3 - Lifecycle] Instantiating Entity: ${data.id}`);
      const positionProperty = new Cesium.ConstantPositionProperty(position);
      const orientationProperty = new Cesium.ConstantProperty(orientation);
      const entity = this.viewer.entities.add({
        id: data.id,
        position: positionProperty,
        orientation: orientationProperty,
        // point: {
        //   pixelSize: 15,
        //   color: Cesium.Color.RED,
        //   outlineColor: Cesium.Color.WHITE,
        //   outlineWidth: 3,
        //   disableDepthTestDistance: Number.POSITIVE_INFINITY
        // }
        model: {
          uri: '/models/ergoninane-fast-71.glb',
          minimumPixelSize: 32,
          maximumScale: 100,
          scale: 0.5,
          show: true,
          runAnimations: true,
          shadows: Cesium.ShadowMode.ENABLED,
          color: Cesium.Color.WHITE,
          colorBlendMode: Cesium.ColorBlendMode.MIX,
          colorBlendAmount: 0.1, // Mix in 20% white to brighten the mesh
        }
      });
      this.entitiesRegistry.set(data.id, entity);
    } else {
      // TASK-017: Conditional Instantiation (Existing)
      const entity = this.entitiesRegistry.get(data.id);
      entity.position.setValue(position);
      entity.orientation.setValue(orientation);
    }
  }

  // TASK-018: Resource Cleanup
  private cleanupStaleEntities(): void {
    if (!this.viewer) return;
    const now = Date.now();
    const threshold = 5000; // 5 seconds timeout threshold

    for (const [id, lastUpdated] of this.lastUpdateRegistry.entries()) {
      if (now - lastUpdated > threshold) {
        const entity = this.entitiesRegistry.get(id);
        if (entity) {
          this.viewer.entities.remove(entity);
          this.entitiesRegistry.delete(id);
        }
        this.lastUpdateRegistry.delete(id);
      }
    }
  }
}
