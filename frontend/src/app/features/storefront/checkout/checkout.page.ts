import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import QRCode from 'qrcode';

import { Bill, BillingService, SessionBills, upiLink } from '../../../core/billing/billing.service';
import { ApiError } from '../../../core/http/api-error';
import { CartService } from '../../../core/ordering/cart.service';
import { CheckoutService } from '../../../core/payments/checkout.service';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { BillSummaryComponent } from './bill-summary.component';

/**
 * Checkout for the table's bill: every charge, then
 *  1. UPI ID, UPI QR or card through Razorpay — confirmed automatically by the signed webhook;
 *  2. the restaurant's own UPI ID (QR + "Open UPI app") — staff confirm when they see the money.
 * After payment the invoice can be downloaded (also later with the order ID + PIN).
 */
@Component({
  selector: 'wl-storefront-checkout',
  imports: [FormsModule, RouterLink, BillSummaryComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../booking-shared.scss'],
  styles: `
    .pay-options { display: grid; gap: 0.9rem; }
    .option { border: 1px solid var(--wl-line); border-radius: 14px; padding: 1rem; display: grid; gap: 0.6rem; }
    .option h2 { margin: 0; font-size: 1.05rem; display: flex; gap: 0.4rem; align-items: center; }
    .option p { margin: 0; }
    .upi { display: grid; grid-template-columns: auto 1fr; gap: 1rem; align-items: center; }
    @media (max-width: 520px) { .upi { grid-template-columns: 1fr; justify-items: center; text-align: center; } }
    .upi img { width: 200px; height: 200px; border-radius: 12px; border: 1px solid var(--wl-line); background: #fff; }
    .vpa { font: 600 1.05rem ui-monospace, monospace; user-select: all; }
    .badges { display: flex; flex-wrap: wrap; gap: 0.35rem; }
    .badges span { font-size: 0.78rem; padding: 0.1rem 0.55rem; border-radius: 999px; background: var(--wl-surface-alt, #f1f1f1); }
    .paid { text-align: center; display: grid; gap: 0.6rem; justify-items: center; }
    .paid .material-symbols-outlined { font-size: 3rem; color: #2e7d4f; }
    .wait { display: flex; gap: 0.6rem; align-items: center; }
    .mock { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; padding: 0.6rem; border: 1px dashed var(--wl-line); border-radius: 10px; }
  `,
  template: `
    <section class="wl-container bk-page">
      <header class="bk-head"><h1>Checkout</h1><p>Pay your bill from your phone.</p></header>
      @if (error(); as e) { <p class="bk-error" role="alert">{{ e }}</p> }

      @if (!cart.tableToken()) {
        <article class="bk-card"><p>Open your table first with the order ID and PIN.</p>
          <div class="bk-actions"><a routerLink="../../session" class="wl-btn wl-btn--primary">Open my table</a></div></article>
      } @else if (!bill()) {
        <div class="wl-state"><span class="wl-spinner" aria-label="Loading"></span></div>
      } @else {
        @let b = bill()!;
        <article class="bk-card"><wl-bill-summary [bill]="b" [currency]="currency()" /></article>

        @if (b.status === 'paid') {
          <article class="bk-card paid" data-testid="checkout-paid">
            <span class="material-symbols-outlined" aria-hidden="true">check_circle</span>
            <h2>Paid — thank you!</h2>
            @for (inv of b.invoices; track inv.id) {
              @if (inv.kind === 'invoice') {
                <a class="wl-btn wl-btn--primary" [href]="receiptUrl(inv.id)" target="_blank" rel="noopener" data-testid="download-invoice">
                  Download invoice {{ inv.number }}</a>
              }
            }
            <p class="bk-muted">You can download it again any time from "Have an order ID?" with your order ID {{ data()?.session_code }} and PIN.</p>
          </article>
        } @else if (pendingUpi()) {
          <article class="bk-card wait" role="status" data-testid="checkout-waiting">
            <span class="wl-spinner" aria-hidden="true"></span>
            <p><b>Waiting for {{ data()?.restaurant_name }} to confirm your UPI payment</b> of {{ price(pendingUpi()!.amount) }}.
              This page updates by itself.</p>
          </article>
        } @else if (+b.due > 0) {
          <div class="pay-options">
            @if (b.methods.includes('gateway')) {
              <article class="option" data-testid="pay-gateway">
                <h2><span class="material-symbols-outlined" aria-hidden="true">credit_card</span> UPI, QR code or card</h2>
                <div class="badges"><span>UPI ID</span><span>UPI QR</span><span>Debit / credit card</span><span>Net banking</span></div>
                @if (mock()) {
                  <div class="mock" role="group" aria-label="Test payment">
                    <span class="bk-muted">Test payment (development) — {{ price(b.due) }}</span>
                    <button type="button" class="wl-btn wl-btn--primary" (click)="mockPay(true)" [disabled]="busy()" data-testid="mock-pay">Pay now</button>
                    <button type="button" class="wl-btn wl-btn--ghost wl-btn--sm" (click)="mockPay(false)" [disabled]="busy()">Fail</button>
                  </div>
                } @else {
                  <button type="button" class="wl-btn wl-btn--primary" (click)="payOnline()" [disabled]="busy()" data-testid="checkout-pay-online">
                    Pay {{ price(b.due) }}</button>
                }
                <p class="bk-muted">Secure payment by Razorpay. Your bill updates as soon as the payment is confirmed.</p>
              </article>
            }
            @if (data()?.upi_id) {
              <article class="option" data-testid="pay-upi-direct">
                <h2><span class="material-symbols-outlined" aria-hidden="true">qr_code_2</span> Pay {{ data()!.upi_payee_name }} by UPI</h2>
                <div class="upi">
                  @if (qr()) { <img [src]="qr()" [alt]="'UPI QR code for ' + price(b.due)" data-testid="upi-qr" /> }
                  <div>
                    <p>Scan with any UPI app, or pay to</p>
                    <p class="vpa" data-testid="upi-id">{{ data()!.upi_id }}</p>
                    <p>Amount <b>{{ price(b.due) }}</b></p>
                    <a class="wl-btn wl-btn--ghost wl-btn--sm" [href]="upi()">Open UPI app</a>
                  </div>
                </div>
                <label class="bk-field"><span>UPI reference / UTR (optional)</span>
                  <input [(ngModel)]="reference" maxlength="80" name="ref" inputmode="numeric" data-testid="upi-ref" /></label>
                <button type="button" class="wl-btn wl-btn--primary" (click)="claimUpi()" [disabled]="busy()" data-testid="upi-paid">I have paid</button>
                <p class="bk-muted">The restaurant confirms it when the money arrives.</p>
              </article>
            }
            <p class="bk-muted center">Prefer cash or card at the table? Ask your waiter.</p>
          </div>
        }
        <div class="bk-actions"><a routerLink="../../session" class="wl-btn wl-btn--ghost wl-btn--sm">Back to my table</a></div>
      }
    </section>
  `,
})
export class StorefrontCheckoutPage implements OnInit {
  readonly billId = input.required<string>();
  protected readonly ctx = inject(TenantContextService);
  protected readonly cart = inject(CartService);
  private readonly api = inject(BillingService);
  private readonly checkout = inject(CheckoutService);
  private readonly realtime = inject(RealtimeService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly data = signal<SessionBills | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly mock = signal<{ orderId: string } | null>(null);
  protected readonly qr = signal<string | null>(null);
  protected reference = '';

  protected readonly bill = computed<Bill | null>(() => this.data()?.bills.find((b) => b.id === this.billId()) ?? null);
  protected readonly pendingUpi = computed(() => this.bill()?.payments.find((p) => p.status === 'pending' && p.method === 'upi') ?? null);
  protected readonly currency = computed(() => this.ctx.restaurant()?.currency ?? 'INR');
  protected readonly upi = computed(() => {
    const d = this.data();
    const b = this.bill();
    return d?.upi_id && b ? upiLink(d.upi_id, d.upi_payee_name, b.due, `Bill ${d.session_code}`) : '';
  });

  ngOnInit(): void {
    this.load();
    const off = this.realtime.on('bills.changed', () => this.load());
    const poll = setInterval(() => this.pendingUpi() && this.load(), 10_000);
    this.destroyRef.onDestroy(() => {
      off();
      clearInterval(poll);
    });
  }

  protected price(v: string | number): string {
    return formatPrice(v, this.currency());
  }

  protected receiptUrl(invoiceId: string): string {
    return this.api.guestReceiptUrl(this.cart.tableToken() ?? '', invoiceId);
  }

  protected payOnline(): void {
    const token = this.cart.tableToken();
    const b = this.bill();
    if (!token || !b) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.payOnline(token, b.id).subscribe({
      next: (p) => {
        this.busy.set(false);
        if (p.checkout.url) {
          this.mock.set({ orderId: p.order_id });
          return;
        }
        void this.checkout.open(p.checkout, { name: this.data()?.restaurant_name, description: 'Your bill' }).then((r) => {
          if (r === 'unavailable') this.error.set('The payment window could not open. Try again or pay your waiter.');
          else if (r === 'submitted') setTimeout(() => this.load(), 2500);
        });
      },
      error: (e: ApiError) => this.fail(e),
    });
  }

  protected mockPay(success: boolean): void {
    const token = this.cart.tableToken();
    const m = this.mock();
    if (!token || !m) return;
    this.busy.set(true);
    this.api.mockPay(token, m.orderId, success).subscribe({
      next: (r) => {
        this.busy.set(false);
        this.mock.set(null);
        if (r.result === 'failed') this.error.set('The payment did not go through. You can try again.');
        this.load();
      },
      error: (e: ApiError) => this.fail(e),
    });
  }

  protected claimUpi(): void {
    const token = this.cart.tableToken();
    const b = this.bill();
    if (!token || !b) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.upiClaim(token, b.id, this.reference).subscribe({
      next: (d) => {
        this.busy.set(false);
        this.data.set(d);
      },
      error: (e: ApiError) => this.fail(e),
    });
  }

  private fail(e: ApiError): void {
    this.busy.set(false);
    this.error.set(e.message);
  }

  private load(): void {
    const token = this.cart.tableToken();
    if (!token) return;
    this.api.guestBills(token).subscribe({
      next: (d) => {
        this.data.set(d);
        const link = this.upi();
        if (link) void QRCode.toDataURL(link, { margin: 1, width: 400 }).then((q) => this.qr.set(q));
      },
      error: (e: ApiError) => this.error.set(e.status === 401 ? 'Your table link has ended. Enter the order ID and PIN again.' : e.message),
    });
  }
}
