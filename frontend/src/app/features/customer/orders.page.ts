import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { BillingService, MyInvoice, openBlob } from '../../core/billing/billing.service';
import { formatWhen } from '../../core/bookings/bookings.service';
import { ApiError } from '../../core/http/api-error';
import { ORDER_STATUS_LABEL, Order, OrderingService } from '../../core/ordering/ordering.service';
import { RealtimeService } from '../../core/realtime/realtime.service';
import { formatPrice } from '../../core/storefront/storefront.models';
import { ServingTimerComponent } from '../../shared/ui/serving-timer/serving-timer.component';

/** Customer "My orders": pre-orders and orders placed while signed in, at every restaurant. */
@Component({
  selector: 'wl-my-orders',
  imports: [RouterLink, ServingTimerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="wl-container bk-page">
      <header class="bk-head">
        <h1>My orders</h1>
        <p>Pre-orders and orders you placed while signed in, and your invoices.</p>
      </header>
      @if (invoices()?.length) {
        <h2 class="sub">Invoices</h2>
        <article class="bk-card inv-list" data-testid="my-invoices">
          @for (i of invoices()!; track i.id) {
            <div class="inv" data-testid="my-invoice">
              <div>
                <b>{{ i.restaurant_name }} · {{ i.kind === 'credit_note' ? 'Credit note' : 'Invoice' }} {{ i.number }}</b>
                <p class="bk-muted">{{ when(i.issued_at) }} · {{ price(i.total) }}{{ i.items.length ? ' · ' + i.items.slice(0, 4).join(', ') + (i.items.length > 4 ? '…' : '') : '' }}</p>
              </div>
              <button type="button" class="wl-btn wl-btn--ghost wl-btn--sm" (click)="download(i)" [disabled]="downloading() === i.id" data-testid="my-invoice-pdf">
                Download</button>
            </div>
          }
        </article>
        <h2 class="sub">Orders</h2>
      }
      @if (error(); as e) { <p class="bk-error" role="alert">{{ e }}</p> }
      @if (!orders()) {
        <div class="wl-state"><span class="wl-spinner" aria-label="Loading"></span></div>
      } @else {
        @for (o of orders()!; track o.id) {
          <article class="bk-card" data-testid="my-order">
            <div class="row">
              <b>{{ o.restaurant_name }} · #{{ o.number }}</b>
              <span class="bk-badge" [attr.data-status]="badge(o)">{{ label[o.status] }}</span>
              <span class="bk-muted right">{{ when(o.placed_at) }}</span>
            </div>
            <p class="bk-muted">
              {{ o.order_type === 'paid_preorder' ? 'Pre-order for booking ' + o.reservation_code : 'At your table' }}
              · {{ price(o.total) }}
              @if (+o.discount_total > 0) { · <b>{{ price(o.discount_total) }} off — you pay {{ price(o.payable_total) }}</b> }
            </p>
            <wl-serving-timer [order]="o" />
            <ul class="lines">
              @for (l of o.items; track l.id) {
                <li>{{ l.quantity }} × {{ l.name }}{{ l.variant_name ? ' (' + l.variant_name + ')' : '' }}</li>
              }
            </ul>
            <div class="bk-actions">
              @if (o.restaurant_slug) {
                <a [routerLink]="['/r', o.restaurant_slug, 'menu']" [queryParams]="o.order_type === 'paid_preorder' && o.reservation_id ? { preorder: o.reservation_id } : {}"
                   class="wl-btn wl-btn--ghost wl-btn--sm">Order more</a>
              }
              @if (o.can_cancel) {
                <button type="button" class="wl-btn wl-btn--ghost wl-btn--sm" (click)="cancel(o)">Cancel</button>
              }
            </div>
          </article>
        } @empty {
          <article class="bk-card"><p class="bk-muted">No orders yet. <a routerLink="/restaurants">Find a restaurant</a></p></article>
        }
      }
    </section>
  `,
  styleUrls: ['../storefront/booking-shared.scss'],
  styles: `
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      align-items: center;
    }
    .right {
      margin-left: auto;
    }
    .sub {
      font-size: 1.1rem;
      margin: 0.5rem 0 0;
    }
    .inv-list {
      display: grid;
      gap: 0.7rem;
    }
    .inv {
      display: flex;
      gap: 0.75rem;
      align-items: center;
      justify-content: space-between;
    }
    .inv p {
      margin: 0.15rem 0 0;
    }
    .lines {
      margin: 0;
      padding-left: 1.1rem;
    }
    a:not(.wl-btn) {
      color: var(--wl-primary);
      font-weight: 600;
    }
  `,
})
export class MyOrdersPage implements OnInit {
  private readonly api = inject(OrderingService);
  private readonly billing = inject(BillingService);
  private readonly realtime = inject(RealtimeService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly label = ORDER_STATUS_LABEL;
  protected readonly when = formatWhen;
  protected readonly orders = signal<Order[] | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly invoices = signal<MyInvoice[] | null>(null);
  protected readonly downloading = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
    void this.realtime.subscribeUser();
    this.destroyRef.onDestroy(this.realtime.on('orders.changed', () => this.load()));
  }

  protected download(i: MyInvoice): void {
    this.downloading.set(i.id);
    this.billing.myInvoicePdf(i.id).subscribe({
      next: (b) => {
        this.downloading.set(null);
        openBlob(b);
      },
      error: (e: ApiError) => {
        this.downloading.set(null);
        this.error.set(e.message);
      },
    });
  }

  protected price(v: string): string {
    return formatPrice(v);
  }

  protected badge(o: Order): string {
    return o.status === 'ready' ? 'notified' : o.status === 'served' ? 'seated' : o.status === 'cancelled' ? 'cancelled' : 'waiting';
  }

  protected cancel(o: Order): void {
    if (!confirm(`Cancel order #${o.number}?`)) return;
    this.api.cancelMine(o.id).subscribe({ next: () => this.load(), error: (e: ApiError) => this.error.set(e.message) });
  }

  private load(): void {
    this.api.myOrders().subscribe({ next: (o) => this.orders.set(o), error: (e: ApiError) => this.error.set(e.message) });
    this.billing.myInvoices().subscribe({ next: (i) => this.invoices.set(i), error: () => this.invoices.set([]) });
  }
}
