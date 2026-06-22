import { Injectable } from '@angular/core';
import { io, Socket } from 'socket.io-client';
import { Subject } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class SocketService {
  private socket: Socket;

  public telemetry$ = new Subject<any>();
  public simMetrics$ = new Subject<any>();
  public agentStatus$ = new Subject<any>();
  public sensorData$ = new Subject<any>();
  public qaResponse$ = new Subject<any>();
  public toast$ = new Subject<any>();

  constructor() {
    this.socket = io('http://localhost:3000');

    this.socket.on('message', (data) => {
      console.log('message', data);
      this.telemetry$.next(data);
    });

    this.socket.on('sim_metrics', (data) => {
      console.log('sim_metrics', data);
      this.simMetrics$.next(data);
    });

    this.socket.on('agent_status', (data) => {
      this.agentStatus$.next(data);
    });

    this.socket.on('sensor_data', (data) => {
      this.sensorData$.next(data);
    });

    this.socket.on('qa_response', (data) => {
      this.qaResponse$.next(data);
    });

    this.socket.on('toast', (data) => {
      this.toast$.next(data);
    });
  }

  sendMessage(message: string): void {
    this.socket.emit('message', message);
  }

  onMessage(callback: (message: any) => void): void {
    this.socket.on('message', callback);
  }

  emitQaQuery(query: string): void {
    this.socket.emit('qa_query', { query });
  }

  emitDensityCommand(minVehicles: number, maxVehicles: number): void {
    this.socket.emit('density_command', {
      min_vehicles: minVehicles,
      max_vehicles: maxVehicles,
    });
  }

  emitOptimizeCommand(scope: string = 'all'): void {
    this.socket.emit('optimize_command', { scope });
  }

  emitScenarioConfig(config: any): void {
    this.socket.emit('scenario_config', config);
  }
}
