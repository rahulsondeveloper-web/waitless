import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiError } from '../../../core/http/api-error';
import { Overview, SuperAdminService } from '../../../core/platform-admin/super-admin.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { ChartComponent, ChartSpec } from '../../../shared/ui/chart/chart.component';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/** Platform overview (PRD §16): restaurants, usage and SaaS revenue at a glance. */
@Component({
  selector: 'wl-sa-overview',
  imports: [RouterLink, ChartComponent, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../super-admin.scss'],
  template: `
    <header class="page-head"><div><h1>Platform overview</h1><p class="muted">Everything running on WaitLess.</p></div></header>
    @if (error(); as e) { <wl-error-state [message]="e.message" (retry)="load()" /> }
    @else if (!data()) { <wl-loading-state /> }
    @else {
      @let d = data()!;
      <section class="tiles" data-testid="overview-tiles">
        <a class="tile" routerLink="../restaurants"><span>Restaurants</span><b>{{ d.restaurants_total }}</b>
          <small>{{ d.restaurants_by_status.active }} active · {{ d.restaurants_by_status.pending }} pending · {{ d.restaurants_by_status.suspended }} suspended</small></a>
        <div class="tile"><span>Branches</span><b>{{ d.branches }}</b></div>
        <div class="tile"><span>Registered customers</span><b>{{ d.customers }}</b></div>
        <div class="tile"><span>Orders · reservations</span><b>{{ d.orders }}</b><small>{{ d.reservations }} reservations</small></div>
        <a class="tile money" routerLink="../subscriptions"><span>SaaS revenue (this month)</span><b>{{ price(d.saas_revenue_month) }}</b>
          <small>{{ price(d.saas_revenue_total) }} all time · MRR {{ price(d.mrr) }}</small></a>
        <a class="tile" routerLink="../subscriptions" [class.warn]="+d.saas_outstanding > 0"><span>Unpaid invoices</span><b>{{ price(d.saas_outstanding) }}</b>
          <small>{{ d.subscriptions_by_status.past_due }} past due · {{ d.subscriptions_expired_30d }} expired (30 days)</small></a>
        <div class="tile"><span>Restaurant sales (this month)</span><b>{{ price(d.restaurant_sales_month) }}</b><small>paid bills on WaitLess</small></div>
        <a class="tile" routerLink="../support" [class.warn]="d.open_tickets > 0"><span>Open support tickets</span><b>{{ d.open_tickets }}</b></a>
      </section>
      <div class="two">
        <section class="panel"><h2>Restaurants by status</h2><wl-chart [spec]="statusChart()" label="Restaurants by status" [height]="220" /></section>
        <section class="panel"><h2>Live subscriptions by plan</h2><wl-chart [spec]="planChart()" label="Subscriptions by plan" [height]="220" /></section>
      </div>
    }
  `,
})
export class SaOverviewPage implements OnInit {
  private readonly api = inject(SuperAdminService);
  protected readonly data = signal<Overview | null>(null);
  protected readonly error = signal<ApiError | null>(null);

  protected readonly statusChart = computed<ChartSpec>(() => {
    const s = this.data()?.restaurants_by_status ?? ({} as Overview['restaurants_by_status']);
    const keys = ['active', 'pending', 'suspended', 'deactivated', 'rejected'] as const;
    return { type: 'bar', labels: keys.map((k) => k[0].toUpperCase() + k.slice(1)), series: [{ name: 'Restaurants', data: keys.map((k) => s[k] ?? 0) }] };
  });
  protected readonly planChart = computed<ChartSpec>(() => {
    const p = this.data()?.subscriptions_by_plan ?? {};
    return { type: 'doughnut', labels: Object.keys(p), series: [{ name: 'Subscriptions', data: Object.values(p) }] };
  });

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.error.set(null);
    this.api.overview().subscribe({ next: (d) => this.data.set(d), error: (e: ApiError) => this.error.set(e) });
  }

  protected price(v: string): string {
    return formatPrice(v);
  }
}
