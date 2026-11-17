import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { AnalyticsService, MONEY_REPORTS, Report, ReportMeta } from '../../../core/analytics/analytics.service';
import { ApiError } from '../../../core/http/api-error';
import { downloadCsv, toCsv } from '../../../core/inventory/inventory.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ChartComponent } from '../../../shared/ui/chart/chart.component';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

const RANGES = [
  { key: '7', label: 'Last 7 days' },
  { key: '14', label: 'Last 14 days' },
  { key: '30', label: 'Last 30 days' },
  { key: 'month', label: 'This month' },
  { key: 'custom', label: 'Custom…' },
];

/** Reports (PRD §15): sales, orders, serving time, discounts, payments, bookings, queue — chart, table, CSV. */
@Component({
  selector: 'wl-reports-page',
  imports: [FormsModule, MatButtonModule, MatIconModule, ChartComponent, LoadingStateComponent, ErrorStateComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../admin-bookings.scss', '../inventory/inventory-forms.scss'],
  styles: `
    .bar { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: end; margin: 1rem 0; }
    .kinds { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.6rem; }
    .kinds button[aria-pressed='true'] { background: var(--wl-primary); color: #fff; }
    .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.6rem; margin: 1rem 0; }
    .tile { background: var(--wl-surface); border: 1px solid var(--wl-line); border-radius: 12px; padding: 0.7rem 0.9rem; }
    .tile b { display: block; font-size: 1.3rem; font-variant-numeric: tabular-nums; }
    .panel { margin-top: 1rem; }
    .scroll { overflow-x: auto; margin-top: 1rem; }
    td.num, th.num { text-align: right; }
  `,
  template: `
    <header class="page-head">
      <div><h1>Reports</h1><p class="muted">How your restaurant is doing — every number can be downloaded.</p></div>
    </header>
    @if (error(); as e) {
      @if (e.status === 402) {
        <wl-empty-state icon="workspace_premium" title="Reports are part of the Professional plan" message="Upgrade to see sales, serving times and more." />
      } @else {
        <wl-error-state [message]="e.message" (retry)="run()" />
      }
    } @else {
      <div class="kinds" role="group" aria-label="Report">
        @for (r of list(); track r.kind) {
          <button mat-stroked-button type="button" [attr.aria-pressed]="kind() === r.kind" (click)="pick(r.kind)" [attr.data-testid]="'report-' + r.kind">
            {{ r.title }}@if (r.feature === 'analytics.advanced') { <mat-icon inline>star</mat-icon> }</button>
        }
      </div>
      <div class="bar">
        @if (branches().length > 1) {
          <label class="field"><span>Branch</span>
            <select [ngModel]="branchId()" (ngModelChange)="branchId.set($event); run()">
              <option [ngValue]="null">All branches</option>
              @for (b of branches(); track b.id) { <option [ngValue]="b.id">{{ b.name }}</option> }
            </select></label>
        }
        <label class="field"><span>Period</span>
          <select [ngModel]="range()" (ngModelChange)="setRange($event)" data-testid="report-range">
            @for (r of ranges; track r.key) { <option [value]="r.key">{{ r.label }}</option> }
          </select></label>
        @if (range() === 'custom') {
          <label class="field"><span>From</span><input type="date" [(ngModel)]="from" /></label>
          <label class="field"><span>To</span><input type="date" [(ngModel)]="to" /></label>
          <button mat-flat-button (click)="run()">Show</button>
        }
        @if (report()) { <button mat-stroked-button (click)="csv()" data-testid="report-csv"><mat-icon>download</mat-icon>CSV</button> }
      </div>

      @if (blocked()) {
        <wl-empty-state icon="workspace_premium" title="Advanced analytics" message="Best-selling dishes and busy hours are part of the Enterprise plan." />
      } @else if (!report()) {
        <wl-loading-state />
      } @else {
        @let r = report()!;
        <div class="tiles" data-testid="report-totals">
          @for (t of totals(); track t[0]) {
            <div class="tile"><span class="muted">{{ t[0] }}</span><b>{{ isMoney(t[1]) ? price(t[1]) : t[1] }}</b></div>
          }
        </div>
        <section class="panel">
          <h2 class="sr-only">{{ r.title }} chart</h2>
          <wl-chart [spec]="r.chart" [label]="r.title + ' chart'" [money]="money()" />
        </section>
        <div class="scroll">
          <table class="table" data-testid="report-table">
            <thead><tr>@for (c of r.columns; track c; let i = $index) { <th [class.num]="i > 0">{{ c }}</th> }</tr></thead>
            <tbody>
              @for (row of r.rows; track $index) {
                <tr>@for (v of row; track $index; let i = $index) { <td [class.num]="i > 0">{{ v ?? '—' }}</td> }</tr>
              } @empty { <tr><td [attr.colspan]="r.columns.length" class="muted">Nothing in this period.</td></tr> }
            </tbody>
          </table>
        </div>
      }
    }
  `,
})
export class ReportsPage implements OnInit {
  private readonly api = inject(AnalyticsService);
  private readonly tenancy = inject(TenancyService);
  protected readonly ranges = RANGES;
  protected readonly list = signal<ReportMeta[]>([]);
  protected readonly kind = signal('sales');
  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly range = signal('14');
  protected readonly report = signal<Report | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly blocked = signal(false);
  protected from = '';
  protected to = '';

  protected readonly money = computed(() => MONEY_REPORTS.has(this.kind()));
  protected readonly totals = computed(() => Object.entries(this.report()?.totals ?? {}));

  ngOnInit(): void {
    this.tenancy.restaurantMe().subscribe((me) => this.branches.set(me.branches.filter((b) => b.is_active)));
    this.api.reports().subscribe({
      next: (l) => {
        this.list.set(l);
        if (l.length && !l.some((r) => r.kind === this.kind())) this.kind.set(l[0].kind);
        this.setRange('14');
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }

  protected pick(kind: string): void {
    this.kind.set(kind);
    this.run();
  }

  protected setRange(key: string): void {
    this.range.set(key);
    if (key === 'custom') return;
    const today = new Date();
    const iso = (d: Date) => d.toLocaleDateString('en-CA');
    this.to = iso(today);
    const start = new Date(today);
    if (key === 'month') start.setDate(1);
    else start.setDate(today.getDate() - (+key - 1));
    this.from = iso(start);
    this.run();
  }

  protected run(): void {
    this.report.set(null);
    this.blocked.set(false);
    this.api.report(this.kind(), { branch_id: this.branchId(), from: this.from, to: this.to }).subscribe({
      next: (r) => this.report.set(r),
      error: (e: ApiError) => (e.status === 402 ? this.blocked.set(true) : this.error.set(e)),
    });
  }

  protected price(v: string): string {
    return formatPrice(v);
  }

  protected isMoney(v: string): boolean {
    return this.money() && /^-?\d+\.\d{2}$/.test(v);
  }

  protected csv(): void {
    const r = this.report();
    if (r) downloadCsv(`${r.kind}-${r.from}-${r.to}.csv`, toCsv(r.columns, r.rows));
  }
}
