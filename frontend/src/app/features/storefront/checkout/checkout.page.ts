import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import QRCode from 'qrcode';

import { Bill, BillingService, SessionBills, equalShares, upiLink } from '../../../core/billing/billing.service';
import { ApiError } from '../../../core/http/api-error';
import { CartService } from '../../../core/ordering/cart.service';
import { GuestServiceApi } from '../../../core/ordering/guest-service.service';
import { CheckoutService } from '../../../core/payments/checkout.service';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { ReviewFormComponent } from '../review/review-form.component';

type Method = 'counter' | 'card' | 'upi';
type SplitMode = 'whole' | 'equal' | 'person';

/**
 * Checkout in the template's "Order at your table" design (design/default-theme/index.html#order):
 * the Checkout card (dine in, table, order summary) and the Payment Method card
 * (Pay at Restaurant · Credit/Debit Card · UPI / Mobile Banking). Card and UPI go through the payment
 * gateway (the development test payment now, Cashfree with keys); the restaurant's own UPI ID is offered
 * under UPI and confirmed by staff. The bill can be paid whole, in equal shares, or one bill per person.
 */
@Component({
  selector: 'wl-storefront-checkout',
  imports: [FormsModule, RouterLink, ReviewFormComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../booking-shared.scss'],
  styles: `
    .head { text-align: center; margin-bottom: 1.6rem; }
    .eyebrow { font-size: 0.78rem; letter-spacing: 0.22em; text-transform: uppercase; color: var(--wl-primary); font-weight: 500; margin: 0 0 0.4rem; }
    .h-serif { font: 600 clamp(1.9rem, 3.5vw, 2.6rem) / 1.1 var(--wl-font-serif); margin: 0; }
    .script { font-family: var(--wl-font-script); font-weight: 400; color: var(--wl-primary); }
    .detail { display: grid; gap: 0.7rem; margin-top: 1rem; }
    .detail p { margin: 0; }
    .upi { display: grid; grid-template-columns: auto 1fr; gap: 1rem; align-items: center; padding-top: 0.8rem; border-top: 1px dashed var(--wl-line); }
    @media (max-width: 520px) { .upi { grid-template-columns: 1fr; justify-items: center; text-align: center; } }
    .upi img { width: 170px; height: 170px; border-radius: 12px; border: 1px solid var(--wl-line); background: #fff; }
    .vpa { font: 600 1rem ui-monospace, monospace; user-select: all; }
    .mock { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; padding: 0.6rem; border: 1px dashed var(--wl-line); border-radius: 10px; }
    .paid { text-align: center; display: grid; gap: 0.7rem; justify-items: center; }
    .paid > .material-symbols-outlined { font-size: 3rem; color: #2e7d4f; }
    .paid h2 { margin: 0; }
    .downloads { display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: center; }
    .wait { display: flex; gap: 0.6rem; align-items: center; }
    .people { display: inline-flex; align-items: center; gap: 0.5rem; }
    .people button { width: 36px; height: 36px; border-radius: 50%; border: 1px solid var(--wl-line); background: var(--wl-bg); font-size: 1.2rem; cursor: pointer; }
    .people b { min-width: 2ch; text-align: center; font-size: 1.1rem; }
    .share { font-family: var(--wl-font-serif); font-size: 1.5rem; font-weight: 700; }
    .bills { display: grid; gap: 0.5rem; margin: 0; padding: 0; list-style: none; }
    .bills li { display: flex; justify-content: space-between; align-items: center; gap: 0.6rem; padding: 0.55rem 0.7rem; border: 1px solid var(--wl-line); border-radius: 10px; }
    .bills li.on { border-color: var(--wl-primary); background: var(--wl-primary-soft); }
    .err { color: #a3321c; }
  `,
  template: `
    <section class="wl-container bk-page">
      <header class="head">
        <p class="eyebrow">Order at your table</p>
        <h1 class="h-serif">From kitchen to <span class="script">your heart</span></h1>
      </header>
      @if (error(); as e) { <p class="bk-error" role="alert">{{ e }}</p> }

      @if (!token) {
        <article class="oc-card"><p>Open your table first with the order ID and PIN.</p>
          <div class="bk-actions"><a routerLink="../../session" class="wl-btn wl-btn--primary">Open my table</a></div></article>
      } @else if (!bill()) {
        <div class="wl-state"><span class="wl-spinner" aria-label="Loading"></span></div>
      } @else {
        @let b = bill()!;
        @let d = data()!;
        <div class="oc-grid">
          <!-- Checkout -->
          <article class="oc-card" data-testid="checkout-card">
            <div class="oc-row">
              <h2 class="oc-title">Checkout</h2>
              <span class="oc-no">#{{ d.session_code }}</span>
            </div>
            <p class="oc-label">Delivery Type</p>
            <div class="oc-pills" role="radiogroup" aria-label="Delivery type">
              <button type="button" class="oc-pill is-active" role="radio" aria-checked="true" disabled>Dine In</button>
            </div>
            <p class="oc-label">Table</p>
            <p class="oc-muted" style="margin:0">{{ d.table_labels.length ? 'Table ' + d.table_labels.join(', ') : d.restaurant_name }}
              · {{ d.party_size }} guests{{ d.bills.length > 1 ? ' · ' + b.label : '' }}</p>
            <p class="oc-label">Order Summary</p>
            <dl class="oc-summary" data-testid="bill-lines">
              @for (l of b.lines; track l.id) {
                <div><dt>{{ l.name }} <span>x{{ l.quantity }}</span>@if (l.ordered_by_name) { <small>{{ l.ordered_by_name }}</small> }</dt>
                  <dd>{{ price(l.line_total) }}</dd></div>
              }
              <div class="oc-summary__sep"><dt>Subtotal</dt><dd>{{ price(b.subtotal) }}</dd></div>
              @if (+b.sla_discount + +b.sla_discount_after_tax > 0) {
                <div class="saved"><dt>Serving-time discount</dt><dd>− {{ price(+b.sla_discount + +b.sla_discount_after_tax) }}</dd></div>
              }
              @if (+b.manual_discount > 0) { <div class="saved"><dt>Discount</dt><dd>− {{ price(b.manual_discount) }}</dd></div> }
              @if (+b.service_charge > 0) {
                <div><dt>Service Charge ({{ +b.service_charge_pct }}%)</dt><dd>{{ price(b.service_charge) }}</dd></div>
              }
              @for (t of b.taxes; track t.rate) {
                @if (+t.cgst > 0 || +t.sgst > 0) {
                  <div><dt>CGST {{ +t.rate / 2 }}%</dt><dd>{{ price(t.cgst) }}</dd></div>
                  <div><dt>SGST {{ +t.rate / 2 }}%</dt><dd>{{ price(t.sgst) }}</dd></div>
                } @else if (+t.tax > 0) {
                  <div><dt>GST {{ +t.rate }}%</dt><dd>{{ price(t.tax) }}</dd></div>
                }
              }
              @if (+b.booking_credit > 0) { <div class="saved"><dt>Booking fee already paid</dt><dd>− {{ price(b.booking_credit) }}</dd></div> }
              @if (+b.round_off !== 0) { <div><dt>Round off</dt><dd>{{ price(b.round_off) }}</dd></div> }
              <div class="oc-summary__total"><dt>Total</dt><dd data-testid="summary-total">{{ price(b.grand_total) }}</dd></div>
              @if (+b.paid_total > 0 && b.status !== 'paid') {
                <div><dt>Paid so far</dt><dd>{{ price(b.paid_total) }}</dd></div>
                <div class="oc-summary__total"><dt>Still to pay</dt><dd>{{ price(b.due) }}</dd></div>
              }
            </dl>
          </article>

          <div class="oc-stack">
            @if (b.status === 'paid') {
              <article class="oc-card paid" data-testid="checkout-paid">
                <span class="material-symbols-outlined" aria-hidden="true">check_circle</span>
                <h2 class="oc-title">Paid — thank you!</h2>
                <div class="downloads">
                  @for (inv of b.invoices; track inv.id) {
                    @if (inv.kind === 'invoice') {
                      <a class="wl-btn wl-btn--primary" [href]="receiptUrl(inv.id)" target="_blank" rel="noopener" data-testid="download-invoice">
                        Download invoice</a>
                      <a class="wl-btn wl-btn--ghost" [href]="receiptUrl(inv.id, true)" target="_blank" rel="noopener" data-testid="download-invoice-names">
                        Download invoice with names</a>
                    }
                  }
                </div>
                @if (d.session_status === 'closed') {
                  <p data-testid="checkout-closed">Your table is closed — this phone no longer keeps your table, order or name.</p>
                } @else if (d.bills.length > 1) {
                  <a class="wl-btn wl-btn--ghost wl-btn--sm" routerLink="../../session">See the other bills</a>
                }
                <p class="bk-muted">Download it again any time: sign in and open My orders, or use order ID {{ d.session_code }} with your PIN.</p>
                @if (token) { <wl-review-form [token]="token" [guestName]="guestName" /> }
              </article>
            } @else if (pendingUpi() && !canShare()) {
              <article class="oc-card wait" role="status" data-testid="checkout-waiting">
                <span class="wl-spinner" aria-hidden="true"></span>
                <p><b>Waiting for {{ d.restaurant_name }} to confirm your UPI payment</b> of {{ price(pendingUpi()!.amount) }}.
                  This page updates by itself.</p>
              </article>
            } @else if (+b.due > 0) {
              <!-- Split the bill -->
              <article class="oc-card" data-testid="split-card">
                <h2 class="oc-title">Split the bill</h2>
                <div class="oc-pills" role="radiogroup" aria-label="How to pay">
                  <button type="button" class="oc-pill" role="radio" [class.is-active]="split() === 'whole'" [attr.aria-checked]="split() === 'whole'"
                          (click)="split.set('whole')" data-testid="split-whole">Whole bill</button>
                  <button type="button" class="oc-pill" role="radio" [class.is-active]="split() === 'equal'" [attr.aria-checked]="split() === 'equal'"
                          (click)="split.set('equal')" data-testid="split-equal">Equal shares</button>
                  <button type="button" class="oc-pill" role="radio" [class.is-active]="split() === 'person'" [attr.aria-checked]="split() === 'person'"
                          (click)="split.set('person')" data-testid="split-person">By person</button>
                </div>
                @switch (split()) {
                  @case ('equal') {
                    <div class="detail">
                      <p class="oc-label" style="margin:0">Split between</p>
                      <div class="people">
                        <button type="button" (click)="setPeople(people() - 1)" aria-label="One person less">−</button>
                        <b data-testid="split-people">{{ people() }}</b>
                        <button type="button" (click)="setPeople(people() + 1)" aria-label="One person more">+</button>
                        <span class="oc-muted">people</span>
                      </div>
                      <p>Your share <span class="share" data-testid="split-share">{{ price(myShare()) }}</span>
                        <span class="oc-muted"> of {{ price(b.grand_total) }}</span></p>
                      <p class="oc-muted">Everyone pays their share from their own phone (same order ID and PIN). The table closes when the last share is paid.</p>
                    </div>
                  }
                  @case ('person') {
                    <div class="detail">
                      @if (d.bills.length > 1) {
                        <p class="oc-muted">Everyone has their own bill — pay yours:</p>
                        <ul class="bills" data-testid="person-bills">
                          @for (x of d.bills; track x.id) {
                            @if (x.lines.length) {
                              <li [class.on]="x.id === b.id">
                                <span><b>{{ owners(x) || x.label }}</b> · {{ price(x.grand_total) }}{{ x.status === 'paid' ? ' · paid' : '' }}</span>
                                @if (x.id !== b.id && x.status !== 'paid') { <a class="wl-btn wl-btn--ghost wl-btn--sm" [routerLink]="['..', x.id]">Pay this</a> }
                              </li>
                            }
                          }
                        </ul>
                      } @else if (canSplitByPerson()) {
                        <p class="oc-muted">Each person gets a bill with only the dishes ordered under their name.</p>
                        <div><button type="button" class="wl-btn wl-btn--ghost" (click)="splitByPerson()" [disabled]="busy()" data-testid="split-by-person">
                          Give everyone their own bill</button></div>
                      } @else {
                        <p class="oc-muted">{{ b.locked ? 'A payment has started on this bill, so it can no longer be split by person.'
                          : 'Every dish was ordered under one name — use equal shares instead.' }}</p>
                      }
                    </div>
                  }
                }
              </article>

              <!-- Payment Method -->
              <article class="oc-card" data-testid="payment-card">
                <h2 class="oc-title">Payment Method</h2>
                <div class="oc-pay" role="radiogroup" aria-label="Payment method">
                  <label class="oc-pay__opt"><input type="radio" name="pay" value="counter" [(ngModel)]="method" data-testid="method-counter" />
                    <span class="material-symbols-outlined" aria-hidden="true">storefront</span>
                    <span><b>Pay at Restaurant</b><small>Cash or card with your waiter</small></span></label>
                  @if (gateway()) {
                    <label class="oc-pay__opt"><input type="radio" name="pay" value="card" [(ngModel)]="method" data-testid="method-card" />
                      <span class="material-symbols-outlined" aria-hidden="true">credit_card</span>
                      <span><b>Credit / Debit Card</b><small>Visa, MasterCard, RuPay, etc.</small></span></label>
                  }
                  @if (gateway() || d.upi_id) {
                    <label class="oc-pay__opt"><input type="radio" name="pay" value="upi" [(ngModel)]="method" data-testid="method-upi" />
                      <span class="material-symbols-outlined" aria-hidden="true">smartphone</span>
                      <span><b>UPI / Mobile Banking</b><small>GPay, PhonePe, Paytm</small></span></label>
                  }
                </div>

                <div class="detail">
                  @switch (method) {
                    @case ('counter') {
                      <p>Your waiter brings the card machine or takes cash at the table.</p>
                      <div><button type="button" class="wl-btn wl-btn--ghost" (click)="askForBill()" [disabled]="busy() || asked()" data-testid="ask-bill">
                        {{ asked() ? 'The waiter is on the way' : 'Ask the waiter for the bill' }}</button></div>
                    }
                    @default {
                      @if (gateway() && (method === 'card' || method === 'upi')) {
                        <div data-testid="pay-gateway">
                          @if (mock()) {
                            <div class="mock" role="group" aria-label="Test payment">
                              <span class="bk-muted">Test payment (development) — {{ price(mock()!.amount) }}</span>
                              <button type="button" class="wl-btn wl-btn--primary" (click)="mockPay(true)" [disabled]="busy()" data-testid="mock-pay">Pay now</button>
                              <button type="button" class="wl-btn wl-btn--ghost wl-btn--sm" (click)="mockPay(false)" [disabled]="busy()">Fail</button>
                            </div>
                          } @else {
                            <button type="button" class="wl-btn wl-btn--primary oc-btn-block" (click)="payOnline()" [disabled]="busy() || !canPay()"
                                    data-testid="checkout-pay-online">
                              Pay {{ price(payAmount()) }}{{ method === 'upi' ? ' by UPI' : ' by card' }}</button>
                          }
                        </div>
                      }
                      @if (method === 'upi' && d.upi_id) {
                        <div class="upi" data-testid="pay-upi-direct">
                          @if (qr()) { <img [src]="qr()" [alt]="'UPI QR code for ' + price(payAmount())" data-testid="upi-qr" /> }
                          <div class="detail" style="margin:0">
                            <p><b>{{ gateway() ? 'Or pay ' : 'Pay ' }}{{ d.upi_payee_name }} directly</b></p>
                            <p class="vpa" data-testid="upi-id">{{ d.upi_id }}</p>
                            <p>Amount <b>{{ price(payAmount()) }}</b></p>
                            <a class="wl-btn wl-btn--ghost wl-btn--sm" [href]="upi()">Open UPI app</a>
                            <label class="oc-label" style="margin:0">UPI reference / UTR <span class="oc-muted">(optional)</span>
                              <input class="oc-input" [(ngModel)]="reference" maxlength="80" name="ref" inputmode="numeric" data-testid="upi-ref" /></label>
                            <div><button type="button" class="wl-btn wl-btn--primary" (click)="claimUpi()" [disabled]="busy() || !canPay()" data-testid="upi-paid">I have paid</button></div>
                            <p class="oc-muted">The restaurant confirms it when the money arrives.</p>
                          </div>
                        </div>
                      }
                    }
                  }
                </div>
                <p class="oc-secure"><span class="material-symbols-outlined" aria-hidden="true">lock</span>
                  Your payment information is secure and encrypted.</p>
              </article>
              @if (pendingUpi(); as pu) {
                <p class="bk-muted" role="status">A UPI payment of {{ price(pu.amount) }} is waiting for the restaurant to confirm.</p>
              }
            }
            <div class="bk-actions"><a routerLink="../../session" class="wl-btn wl-btn--ghost wl-btn--sm">Back to my table</a></div>
          </div>
        </div>
      }
    </section>
  `,
})
export class StorefrontCheckoutPage implements OnInit {
  readonly billId = input.required<string>();
  protected readonly ctx = inject(TenantContextService);
  protected readonly cart = inject(CartService);
  /** Kept for this page even after the visit ends and the browser forgets it (invoice links still work). */
  protected readonly token = this.cart.tableToken();
  protected readonly guestName = this.cart.guestName();
  private readonly api = inject(BillingService);
  private readonly service = inject(GuestServiceApi);
  private readonly checkout = inject(CheckoutService);
  private readonly realtime = inject(RealtimeService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly data = signal<SessionBills | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly mock = signal<{ orderId: string; amount: string } | null>(null);
  protected readonly qr = signal<string | null>(null);
  protected readonly split = signal<SplitMode>('whole');
  protected readonly people = signal(2);
  protected readonly asked = signal(false);
  protected method: Method = 'card';
  protected reference = '';

  protected readonly bill = computed<Bill | null>(() => this.data()?.bills.find((b) => b.id === this.billId()) ?? null);
  protected readonly gateway = computed(() => !!this.bill()?.methods.includes('gateway'));
  protected readonly pendingUpi = computed(() => this.bill()?.payments.find((p) => p.status === 'pending' && p.method === 'upi') ?? null);
  protected readonly currency = computed(() => this.ctx.restaurant()?.currency ?? 'INR');
  /** One person's equal share of the whole bill (never more than what is still due). */
  protected readonly myShare = computed(() => {
    const b = this.bill();
    if (!b) return '0';
    const share = +equalShares(b.grand_total, this.people())[0];
    return Math.min(share, +b.due).toFixed(2);
  });
  protected readonly payAmount = computed(() => (this.split() === 'equal' ? this.myShare() : this.bill()?.due ?? '0'));
  protected readonly canPay = computed(() => +this.payAmount() > 0);
  protected readonly canShare = computed(() => this.split() === 'equal');
  protected readonly canSplitByPerson = computed(() => {
    const b = this.bill();
    return !!b && !b.locked && new Set(b.lines.map((l) => l.ordered_by_name).filter(Boolean)).size > 1;
  });
  protected readonly upi = computed(() => {
    const d = this.data();
    return d?.upi_id ? upiLink(d.upi_id, d.upi_payee_name, this.payAmount(), `Bill ${d.session_code}`) : '';
  });

  ngOnInit(): void {
    this.load();
    const off = this.realtime.on('bills.changed', () => this.load());
    const poll = setInterval(() => this.pendingUpi() && this.load(), 10_000);
    // Live updates for this table (a share paid on another phone, the cashier taking cash, UPI confirmed).
    const token = this.token;
    if (token) void this.realtime.subscribeTableSession(token);
    this.destroyRef.onDestroy(() => {
      off();
      clearInterval(poll);
      if (token) this.realtime.unsubscribeTableSession(token);
    });
  }

  protected price(v: string | number): string {
    return formatPrice(v, this.currency());
  }

  protected receiptUrl(invoiceId: string, names = false): string {
    return this.api.guestReceiptUrl(this.token ?? '', invoiceId, names);
  }

  protected owners(b: Bill): string {
    return [...new Set(b.lines.map((l) => l.ordered_by_name).filter(Boolean))].join(', ');
  }

  protected setPeople(n: number): void {
    this.people.set(Math.max(2, Math.min(20, n)));
    this.refreshQr();
  }

  protected askForBill(): void {
    if (!this.token) return;
    this.busy.set(true);
    this.service.call(this.token, 'bill', this.guestName).subscribe({
      next: () => {
        this.busy.set(false);
        this.asked.set(true);
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        if (e.code === 'CALL_COOLDOWN') this.asked.set(true);
        else this.error.set(e.message);
      },
    });
  }

  protected splitByPerson(): void {
    const b = this.bill();
    if (!this.token || !b) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.splitByPerson(this.token, b.id).subscribe({
      next: (d) => {
        this.busy.set(false);
        this.data.set(d);
      },
      error: (e: ApiError) => this.fail(e),
    });
  }

  protected payOnline(): void {
    const token = this.token;
    const b = this.bill();
    if (!token || !b) return;
    this.busy.set(true);
    this.error.set(null);
    const share = this.split() === 'equal' ? this.myShare() : null;
    this.api.payOnline(token, b.id, share).subscribe({
      next: (p) => {
        this.busy.set(false);
        if (p.checkout.url) {
          this.mock.set({ orderId: p.order_id, amount: p.amount });
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
    const token = this.token;
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
    const token = this.token;
    const b = this.bill();
    if (!token || !b) return;
    this.busy.set(true);
    this.error.set(null);
    const share = this.split() === 'equal' ? this.myShare() : null;
    this.api.upiClaim(token, b.id, this.reference, share).subscribe({
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

  private refreshQr(): void {
    const link = this.upi();
    if (link) void QRCode.toDataURL(link, { margin: 1, width: 360 }).then((q) => this.qr.set(q));
  }

  private load(): void {
    const token = this.token;
    if (!token) return;
    this.api.guestBills(token).subscribe({
      next: (d) => {
        const first = !this.data();
        this.data.set(d);
        if (first) {
          this.people.set(Math.max(2, d.party_size || 2));
          if (!this.gateway()) this.method = d.upi_id ? 'upi' : 'counter';
        }
        if (d.session_status === 'closed' && this.cart.tableToken() === token) {
          // Paid in full → the visit closed: clear the browser's table data, keep this page's invoice links.
          this.cart.endVisit({
            code: d.session_code,
            restaurantName: d.restaurant_name,
            receipts: d.bills.flatMap((b) =>
              b.invoices
                .filter((i) => i.kind === 'invoice')
                .map((i) => ({ number: i.number, url: this.receiptUrl(i.id), namesUrl: this.receiptUrl(i.id, true) })),
            ),
            token,
            guestName: this.guestName,
          });
        }
        this.refreshQr();
      },
      error: (e: ApiError) => this.error.set(e.status === 401 ? 'Your table link has ended. Enter the order ID and PIN again.' : e.message),
    });
  }
}
