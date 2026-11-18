import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { interval } from 'rxjs';

import { BillingService, SessionBills } from '../../../core/billing/billing.service';
import { ApiError } from '../../../core/http/api-error';
import { CartService } from '../../../core/ordering/cart.service';
import { ORDER_STATUS_LABEL, Order, OrderingService, TableView } from '../../../core/ordering/ordering.service';
import { promiseText } from '../../../core/ordering/sla';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { ServingTimerComponent } from '../../../shared/ui/serving-timer/serving-timer.component';
import { BillSummaryComponent } from '../checkout/bill-summary.component';
import { CheckoutService } from '../../../core/payments/checkout.service';

const STEPS = ['placed', 'accepted', 'preparing', 'ready', 'served'] as const;

/**
 * "Have an order ID?" (PRD §13): guests enter the code + PIN the waiter gave them, then see their
 * orders, the serving timer and any delay discount (PRD §14), the running total live, and can order more.
 */
@Component({
  selector: 'wl-storefront-session',
  imports: [FormsModule, RouterLink, ServingTimerComponent, BillSummaryComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './session.page.html',
  styleUrls: ['../booking-shared.scss', './session.page.scss'],
})
export class StorefrontSessionPage implements OnInit {
  protected readonly ctx = inject(TenantContextService);
  protected readonly cart = inject(CartService);
  private readonly api = inject(OrderingService);
  private readonly billing = inject(BillingService);
  private readonly checkout = inject(CheckoutService);
  private readonly realtime = inject(RealtimeService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly router = inject(Router);

  protected readonly statusLabel = ORDER_STATUS_LABEL;
  protected readonly steps = STEPS;
  protected readonly view = signal<TableView | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly loading = signal(false);
  protected readonly now = signal(Date.now());
  /** server time − device time, so the countdown is right even on a phone with a wrong clock */
  protected readonly offset = signal(0);
  protected readonly promiseText = promiseText;
  /** The bill (Phase 10): after Finish, or as soon as staff generate it. null = billing not available. */
  protected readonly bills = signal<SessionBills | null>(null);
  protected readonly paying = signal<{ billId: string; orderId: string; amount: string; mock: boolean } | null>(null);
  protected readonly billBusy = signal(false);
  /** The Finish popup: 'confirm' asks first, 'bill' shows the final bill with Pay now. */
  protected readonly popup = signal<'confirm' | 'bill' | null>(null);
  protected readonly payable = computed(() => (this.bills()?.bills ?? []).filter((b) => b.lines.length && b.status !== 'void'));
  protected code = '';
  protected guestName = '';
  protected pin = '';
  private watching: string | null = null;

  protected readonly active = computed(() => (this.view()?.orders ?? []).filter((o) => o.status !== 'cancelled'));

  ngOnInit(): void {
    if (this.cart.tableToken()) this.load();
    const off = this.realtime.on<{ order_id: string }>('orders.changed', () => this.load(false));
    const offBills = this.realtime.on('bills.changed', () => this.loadBills());
    interval(30_000)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.now.set(Date.now());
        if (this.cart.tableToken()) this.load(false);
      });
    this.destroyRef.onDestroy(() => {
      off();
      offBills();
      if (this.watching) this.realtime.unsubscribeTableSession(this.watching);
    });
  }

  protected join(): void {
    const slug = this.ctx.slug();
    if (!slug) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.joinTable(slug, this.code.trim().toUpperCase(), this.pin.trim()).subscribe({
      next: (r) => {
        this.busy.set(false);
        this.cart.setPreorder(null);
        this.cart.setTableToken(r.token);
        if (this.guestName.trim()) this.cart.setGuestName(this.guestName);
        this.pin = '';
        this.load();
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.code === 'RATE_LIMITED' ? 'Too many tries. Please ask your waiter for help.' : e.message);
      },
    });
  }

  protected leave(): void {
    if (this.watching) this.realtime.unsubscribeTableSession(this.watching);
    this.watching = null;
    this.cart.setTableToken(null);
    this.view.set(null);
    this.bills.set(null);
  }

  // ---------- the bill ----------

  protected finish(): void {
    this.popup.set('confirm');
  }

  protected closePopup(): void {
    this.popup.set(null);
  }

  protected payNow(billId: string): void {
    this.popup.set(null);
    void this.router.navigate(['/r', this.ctx.slug(), 'checkout', billId]);
  }

  protected confirmFinish(): void {
    const token = this.cart.tableToken();
    if (!token) return;
    this.billBusy.set(true);
    this.billing.finish(token).subscribe({
      next: (b) => {
        this.billBusy.set(false);
        this.bills.set(b);
        this.popup.set('bill');
        this.load(false);
      },
      error: (e: ApiError) => {
        this.billBusy.set(false);
        this.popup.set(null);
        this.error.set(e.message);
      },
    });
  }

  protected payOnline(billId: string): void {
    const token = this.cart.tableToken();
    if (!token) return;
    this.billBusy.set(true);
    this.error.set(null);
    this.billing.payOnline(token, billId).subscribe({
      next: (p) => {
        this.billBusy.set(false);
        if (p.checkout.url) {
          this.paying.set({ billId, orderId: p.order_id, amount: p.amount, mock: true });
          return;
        }
        void this.checkout
          .open(p.checkout, { name: this.view()?.restaurant_name ?? 'WaitLess', description: 'Your bill' })
          .then((r) => {
            if (r === 'unavailable') this.error.set('The payment window could not open. Please pay your waiter or try again.');
            else if (r === 'submitted') setTimeout(() => this.loadBills(), 2500); // the webhook marks it paid
          });
      },
      error: (e: ApiError) => {
        this.billBusy.set(false);
        this.error.set(e.message);
      },
    });
  }

  /** Development only (mock gateway): simulate the payment page. */
  protected mockPay(success: boolean): void {
    const token = this.cart.tableToken();
    const p = this.paying();
    if (!token || !p) return;
    this.billBusy.set(true);
    this.billing.mockPay(token, p.orderId, success).subscribe({
      next: (r) => {
        this.billBusy.set(false);
        this.paying.set(null);
        if (r.result === 'failed') this.error.set('The payment did not go through. You can try again or pay at the counter.');
        this.loadBills();
      },
      error: (e: ApiError) => {
        this.billBusy.set(false);
        this.error.set(e.message);
      },
    });
  }

  protected receiptUrl(invoiceId: string): string {
    return this.billing.guestReceiptUrl(this.cart.tableToken() ?? '', invoiceId);
  }

  protected n(v: string): number {
    return +v;
  }

  private loadBills(): void {
    const token = this.cart.tableToken();
    if (!token) return;
    this.billing.guestBills(token).subscribe({ next: (b) => this.bills.set(b), error: () => this.bills.set(null) });
  }

  protected cancel(o: Order): void {
    const token = this.cart.tableToken();
    if (!token || !confirm(`Cancel order #${o.number}?`)) return;
    this.api.tableCancel(token, o.id).subscribe({ next: () => this.load(false), error: (e: ApiError) => this.error.set(e.message) });
  }

  protected price(v: string | number): string {
    return formatPrice(v, this.ctx.restaurant()?.currency ?? 'INR');
  }

  protected minutes(o: Order): number {
    const end = o.served_at ? Date.parse(o.served_at) : this.now();
    return Math.max(0, Math.floor((end - Date.parse(o.placed_at)) / 60_000));
  }

  protected addonNames(l: Order['items'][number]): string {
    return l.addons.map((a) => a.name).join(', ');
  }

  protected stepIndex(o: Order): number {
    return STEPS.indexOf(o.status as (typeof STEPS)[number]);
  }

  private load(showSpinner = true): void {
    const token = this.cart.tableToken();
    if (!token) return;
    if (showSpinner) this.loading.set(true);
    this.api.tableView(token).subscribe({
      next: (v) => {
        this.loading.set(false);
        if (v.restaurant_slug !== this.ctx.slug()) {
          this.leave(); // a token from another restaurant never shows here
          return;
        }
        this.offset.set(Date.parse(v.server_time) - Date.now());
        this.view.set(v);
        this.loadBills();
        if (this.watching !== token) {
          this.watching = token;
          void this.realtime.subscribeTableSession(token);
        }
      },
      error: (e: ApiError) => {
        this.loading.set(false);
        if (e.status === 401) {
          this.leave();
          this.error.set('Your table link has ended. Enter the code and PIN again.');
        } else this.error.set(e.message);
      },
    });
  }
}
