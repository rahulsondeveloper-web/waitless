import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  afterNextRender,
  effect,
  input,
  viewChild,
} from '@angular/core';
import type { Chart as ChartJs, ChartConfiguration } from 'chart.js';

export interface ChartSpec {
  type: 'bar' | 'line' | 'doughnut';
  labels: string[];
  series: { name: string; data: (number | null)[] }[];
  stacked?: boolean;
  horizontal?: boolean;
}

const PALETTE = ['#0a7c86', '#f2b134', '#c0442b', '#5b6573', '#2e7d4f', '#7a4fb3', '#d97706', '#0ea5e9'];

/**
 * Chart.js wrapper (loaded on demand, so pages without charts stay small).
 * The data table next to every chart carries the same numbers for screen readers and CSV.
 */
@Component({
  selector: 'wl-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div class="box" [style.height.px]="height()"><canvas #canvas role="img" [attr.aria-label]="label()"></canvas></div>`,
  styles: `
    .box { position: relative; width: 100%; }
  `,
})
export class ChartComponent implements OnDestroy {
  readonly spec = input.required<ChartSpec>();
  readonly label = input('Chart');
  readonly height = input(260);
  readonly money = input(false);

  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  private chart: ChartJs | null = null;
  private ready = false;

  constructor() {
    afterNextRender(() => {
      this.ready = true;
      void this.draw();
    });
    effect(() => {
      this.spec();
      if (this.ready) void this.draw();
    });
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  private async draw(): Promise<void> {
    const { Chart } = await import('chart.js/auto');
    const s = this.spec();
    const style = getComputedStyle(document.documentElement);
    const text = style.getPropertyValue('--wl-text').trim() || '#2b2f36';
    const grid = style.getPropertyValue('--wl-line').trim() || '#e5e7eb';
    const money = this.money();
    const fmt = (v: number) =>
      money ? new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v) : String(v);
    const doughnut = s.type === 'doughnut';
    const config: ChartConfiguration = {
      type: s.type,
      data: {
        labels: s.labels,
        datasets: s.series.map((d, i) => ({
          label: d.name,
          data: d.data,
          backgroundColor: doughnut ? PALETTE : PALETTE[i % PALETTE.length] + (s.type === 'line' ? '33' : 'cc'),
          borderColor: doughnut ? '#fff' : PALETTE[i % PALETTE.length],
          borderWidth: s.type === 'line' ? 2 : 1,
          tension: 0.3,
          fill: s.type === 'line',
          borderRadius: s.type === 'bar' ? 4 : 0,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? false : { duration: 300 },
        indexAxis: s.horizontal ? 'y' : 'x',
        plugins: {
          legend: { display: s.series.length > 1 || doughnut, labels: { color: text } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(Number(c.raw ?? 0))}` } },
        },
        scales: doughnut
          ? {}
          : {
              x: { stacked: !!s.stacked, ticks: { color: text, maxRotation: 0, autoSkip: true }, grid: { color: grid } },
              y: { stacked: !!s.stacked, beginAtZero: true, ticks: { color: text, callback: (v) => fmt(Number(v)) }, grid: { color: grid } },
            },
      },
    };
    this.chart?.destroy();
    this.chart = new Chart(this.canvas().nativeElement, config);
  }
}
