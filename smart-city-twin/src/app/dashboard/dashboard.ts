import {
  Component,
  OnInit,
  OnDestroy,
  signal,
  computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NgxEchartsDirective } from 'ngx-echarts';
import { Subscription } from 'rxjs';
import { SocketService } from '../services/socket';
import type { EChartsOption } from 'echarts';

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  confidence?: number;
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, NgxEchartsDirective],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.css',
})
export class Dashboard implements OnInit, OnDestroy {
  private subs: Subscription[] = [];

  // ── Chart collapse state ────────────────────────────────────────
  collapsed = signal(false);

  // ── Line Chart: vehicles vs speed over time ─────────────────────
  lineChartOption = signal<EChartsOption>({});
  private timeLabels: string[] = [];
  private vehicleSeries: number[] = [];
  private speedSeries: number[] = [];

  // ── Radar Chart: business metrics ───────────────────────────────
  radarChartOption = signal<EChartsOption>({});

  // ── Bar Chart: sensor vehicle counts ────────────────────────────
  barChartOption = signal<EChartsOption>({});

  // ── Gauge Chart: density percentage ─────────────────────────────
  gaugeChartOption = signal<EChartsOption>({});

  // ── NLP Chat ────────────────────────────────────────────────────
  chatMessages = signal<ChatMessage[]>([]);
  chatInput = '';
  chatOpen = signal(false);

  // ── Controls ────────────────────────────────────────────────────
  densityMin = 10;
  densityMax = 50;

  // ── Toast ───────────────────────────────────────────────────────
  toasts = signal<{ type: string; title: string; message: string; id: number }[]>([]);
  private toastId = 0;

  constructor(private socket: SocketService) {}

  ngOnInit(): void {
    this._initCharts();

    // sim_metrics → Line chart
    this.subs.push(
      this.socket.simMetrics$.subscribe((data) => {
        if (data.type === 'sim_summary') {
          this._updateLineChart(data);
        }
        if (data.type === 'analytics_snapshot' && data.business_metrics) {
          this._updateRadarChart(data.business_metrics);
        }
      })
    );

    // agent_status → Gauge chart (density)
    this.subs.push(
      this.socket.agentStatus$.subscribe((data) => {
        if (data.agents) {
          const spawner = data.agents.find(
            (a: any) => a.name === 'AdaptiveSpawningAgent'
          );
          if (spawner?.density_pct != null) {
            this._updateGaugeChart(spawner.density_pct);
          }
        }
      })
    );

    // sensor_data → Bar chart
    this.subs.push(
      this.socket.sensorData$.subscribe((data) => {
        if (data.counts) {
          this._updateBarChart(data.counts);
        }
      })
    );

    // QA response
    this.subs.push(
      this.socket.qaResponse$.subscribe((data) => {
        this.chatMessages.update((msgs) => [
          ...msgs,
          {
            role: 'assistant',
            text: data.answer || 'No answer received.',
            confidence: data.confidence,
          },
        ]);
      })
    );

    // Toast notifications
    this.subs.push(
      this.socket.toast$.subscribe((data) => {
        this._addToast(data.type, data.title, data.message);
      })
    );
  }

  ngOnDestroy(): void {
    this.subs.forEach((s) => s.unsubscribe());
  }

  // ── Chart initialization ────────────────────────────────────────

  private _initCharts(): void {
    this.lineChartOption.set({
      tooltip: { trigger: 'axis' },
      legend: {
        data: ['Vehicles', 'Avg Speed (km/h)'],
        textStyle: { color: '#ccc' },
      },
      grid: { left: 40, right: 20, top: 35, bottom: 25 },
      xAxis: {
        type: 'category',
        data: [],
        axisLabel: { color: '#999', fontSize: 10 },
        axisLine: { lineStyle: { color: '#555' } },
      },
      yAxis: [
        {
          type: 'value',
          name: 'Vehicles',
          nameTextStyle: { color: '#999' },
          axisLabel: { color: '#999' },
          splitLine: { lineStyle: { color: '#333' } },
        },
        {
          type: 'value',
          name: 'km/h',
          nameTextStyle: { color: '#999' },
          axisLabel: { color: '#999' },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'Vehicles',
          type: 'line',
          smooth: true,
          data: [],
          itemStyle: { color: '#5470c6' },
          areaStyle: { color: 'rgba(84,112,198,0.15)' },
        },
        {
          name: 'Avg Speed (km/h)',
          type: 'line',
          smooth: true,
          yAxisIndex: 1,
          data: [],
          itemStyle: { color: '#91cc75' },
          areaStyle: { color: 'rgba(145,204,117,0.15)' },
        },
      ],
    });

    this.radarChartOption.set({
      tooltip: {},
      radar: {
        indicator: [
          { name: 'Risk', max: 100 },
          { name: 'Utilization', max: 100 },
          { name: 'Throughput', max: 100 },
          { name: 'Delay', max: 100 },
        ],
        axisName: { color: '#ccc' },
        splitLine: { lineStyle: { color: '#444' } },
        splitArea: { areaStyle: { color: ['rgba(255,255,255,0.02)', 'rgba(255,255,255,0.05)'] } },
      },
      series: [
        {
          type: 'radar',
          data: [{ value: [0, 0, 0, 0], name: 'Profile' }],
          areaStyle: { color: 'rgba(250,200,88,0.2)' },
          lineStyle: { color: '#fac858' },
          itemStyle: { color: '#fac858' },
        },
      ],
    });

    this.barChartOption.set({
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 10, top: 10, bottom: 25 },
      xAxis: {
        type: 'category',
        data: [],
        axisLabel: { color: '#999', fontSize: 9, rotate: 30 },
        axisLine: { lineStyle: { color: '#555' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#999' },
        splitLine: { lineStyle: { color: '#333' } },
      },
      series: [
        {
          type: 'bar',
          data: [],
          itemStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: '#ee6666' },
                { offset: 1, color: '#5470c6' },
              ],
            } as any,
          },
        },
      ],
    });

    this.gaugeChartOption.set({
      series: [
        {
          type: 'gauge',
          startAngle: 220,
          endAngle: -40,
          min: 0,
          max: 100,
          detail: {
            formatter: '{value}%',
            fontSize: 18,
            color: '#fff',
            offsetCenter: [0, '60%'],
          },
          axisLine: {
            lineStyle: {
              width: 15,
              color: [
                [0.3, '#91cc75'],
                [0.7, '#fac858'],
                [1, '#ee6666'],
              ],
            },
          },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          pointer: { width: 4, length: '60%', itemStyle: { color: '#fff' } },
          title: {
            show: true,
            offsetCenter: [0, '85%'],
            color: '#ccc',
            fontSize: 12,
          },
          data: [{ value: 0, name: 'Density' }],
        },
      ],
    });
  }

  // ── Chart update methods ────────────────────────────────────────

  private _updateLineChart(data: any): void {
    const label = Math.round(data.sim_time) + 's';
    this.timeLabels.push(label);
    this.vehicleSeries.push(data.total_vehicles);
    this.speedSeries.push(data.avg_speed_kmh);

    const maxPoints = 30;
    if (this.timeLabels.length > maxPoints) {
      this.timeLabels.shift();
      this.vehicleSeries.shift();
      this.speedSeries.shift();
    }

    this.lineChartOption.set({
      ...this.lineChartOption(),
      xAxis: { ...( this.lineChartOption() as any).xAxis, data: [...this.timeLabels] },
      series: [
        { ...(this.lineChartOption() as any).series[0], data: [...this.vehicleSeries] },
        { ...(this.lineChartOption() as any).series[1], data: [...this.speedSeries] },
      ],
    });
  }

  private _updateRadarChart(bm: any): void {
    const risk = Math.min(100, (bm.safety_risk_score ?? bm.risk ?? 0) * 100);
    const util = Math.min(100, (bm.network_utilization ?? bm.utilization ?? 0) * 100);
    const throughput = Math.min(100, (bm.throughput_veh_per_min ?? bm.throughput ?? 0) * 2);
    const delay = Math.min(100, (bm.avg_travel_delay_s ?? bm.delay ?? 0));

    this.radarChartOption.set({
      ...this.radarChartOption(),
      series: [
        {
          type: 'radar',
          data: [{ value: [risk, util, throughput, delay], name: 'Profile' }],
          areaStyle: { color: 'rgba(250,200,88,0.2)' },
          lineStyle: { color: '#fac858' },
          itemStyle: { color: '#fac858' },
        },
      ],
    });
  }

  private _updateBarChart(counts: Record<string, number>): void {
    const labels = Object.keys(counts).map((k) =>
      k.replace('cctv_', '').replace(/_/g, ' ')
    );
    const values = Object.values(counts);

    this.barChartOption.set({
      ...this.barChartOption(),
      xAxis: { ...(this.barChartOption() as any).xAxis, data: labels },
      series: [{ ...(this.barChartOption() as any).series[0], data: values }],
    });
  }

  private _updateGaugeChart(pct: number): void {
    this.gaugeChartOption.set({
      series: [
        {
          ...(this.gaugeChartOption() as any).series[0],
          data: [{ value: pct, name: 'Density' }],
        },
      ],
    });
  }

  // ── Chat methods ────────────────────────────────────────────────

  toggleChat(): void {
    this.chatOpen.update((v) => !v);
  }

  sendChat(): void {
    const text = this.chatInput.trim();
    if (!text) return;
    this.chatMessages.update((msgs) => [...msgs, { role: 'user', text }]);
    this.socket.emitQaQuery(text);
    this.chatInput = '';
  }

  onChatKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendChat();
    }
  }

  // ── Control methods ─────────────────────────────────────────────

  applyDensity(): void {
    this.socket.emitDensityCommand(this.densityMin, this.densityMax);
  }

  triggerOptimize(): void {
    this.socket.emitOptimizeCommand('all');
  }

  toggleCollapse(): void {
    this.collapsed.update((v) => !v);
  }

  // ── Toast methods ───────────────────────────────────────────────

  private _addToast(type: string, title: string, message: string): void {
    const id = ++this.toastId;
    this.toasts.update((t) => [...t, { type, title, message, id }]);
    setTimeout(() => {
      this.toasts.update((t) => t.filter((x) => x.id !== id));
    }, 5000);
  }

  dismissToast(id: number): void {
    this.toasts.update((t) => t.filter((x) => x.id !== id));
  }
}
