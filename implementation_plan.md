# Backend Agents & Analytics Echarts Dashboard Integration Plan

This plan details the integration of the advanced agents (Analytics, Sensor Manager, Adaptive Spawning, etc.) from your `SmartCityDigitalTwin` repository into the new Linz 3D City map, visualizing their outputs using an **Echarts** dashboard.

## 1. Feature to Echarts Mapping

We will map the exact JSON payloads from the existing backend agents into corresponding Echarts configurations:

| Backend Feature / Agent | Output Event / Data Format | Recommended Echarts Component | Rationale |
| :--- | :--- | :--- | :--- |
| **Analytics Agent** (Global) | `sim_metrics` -> `total_vehicles`, `avg_speed_cms` | **Real-time Line Chart** | Perfect for plotting continuous time-series data (e.g. speed dropping as vehicles increase). |
| **Analytics Agent** (Risk) | `sim_metrics` -> `risk_profile`, `speed_violation_pct` | **Radar Chart** | Ideal for displaying multidimensional business metrics (Safety, Utilization, Efficiency) simultaneously. |
| **Sensor Manager** | `sensor_data` -> `vehicle_count` by sensor ID | **Dynamic Bar Chart** | Bars easily compare the volume throughput of different loop detectors across the city. |
| **Hazard & Incident Agent** | `sim_metrics` -> `incident_assessment` | **Doughnut / Pie Chart** | Visualizes the proportion of different active incident types or severity levels. |
| **Adaptive Spawning Agent** | `agent_status` -> `utilization_ratio` | **Gauge Chart** | Shows current network load as a percentage of the maximum allowed vehicles, like a speedometer. |

## 2. Proposed Dashboard Layout

The UI will be a sleek, transparent **Glassmorphism Overlay** on top of the Cesium map.
- **Left Panel**: AI UrbanQA Chatbox and Global KPIs (Total Vehicles, Active Incidents).
- **Bottom Panel**: Wide Echarts Line Chart showing the timeline of Traffic Speed vs Volume.
- **Right Panel**: Echarts Radar Chart (Risk Profile), Echarts Bar Chart (Sensor Activity), and Control Sliders (Density control sending `density_command`).

## 3. Implementation Steps

### Phase A: Backend Porting (`webgis-backend`)
- Copy the `Sumo_Aligned_Scripts/agents` folder from your previous project into the `webgis-backend` directory.
- Update `sumo_webgis.py` to instantiate the `AgentManager`, `AnalyticsAgent`, and `SensorManager`.
- Hook TraCI step ticks into the agents so they begin analyzing the Linz network and emitting `sim_metrics` over the existing Socket.IO server.

### Phase B: Frontend Setup (`smart-city-twin`)
- Run `npm install echarts ngx-echarts` to add the charting libraries.
- Update `socket.service.ts` to listen for the new agent events (`sim_metrics`, `agent_status`, `toast`).

### Phase C: Dashboard Construction
- Create a new Angular component `app-dashboard`.
- Initialize the mapped Echarts configurations (`EChartsOption`).
- Feed the real-time socket data into the Echarts `setOption` methods to create live, animated visualizations.

## User Review Required

> [!IMPORTANT]
> 1. Do you want me to port the exact python agent files over to the `webgis-backend` directory so everything is localized, or should the backend reference them via an absolute path from the old project? (I recommend copying them locally).
> 2. Are you satisfied with the proposed Echarts mapping (Line, Radar, Bar, Gauge)? 

Once approved, I will begin the backend porting and install Echarts!
