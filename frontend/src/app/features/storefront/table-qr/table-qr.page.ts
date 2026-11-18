import { ChangeDetectionStrategy, Component, OnInit, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { CartService } from '../../../core/ordering/cart.service';
import { OrderingService, QrSeat, QrTable } from '../../../core/ordering/ordering.service';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';

/**
 * Landing page of the QR code printed on a table (/r/:slug/t/:qr).
 * Free table → the guest gives a name and opens it (gets the order ID + PIN to share with friends).
 * Taken table → friends join with the PIN. Either way they land on the menu, ordering for this table.
 */
@Component({
  selector: 'wl-storefront-table-qr',
  imports: [FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../booking-shared.scss'],
  styles: `
    .table { font-size: 2.2rem; font-weight: 700; margin: 0; }
    .codes { display: flex; gap: 1.5rem; flex-wrap: wrap; }
    .codes b { display: block; font: 700 1.6rem ui-monospace, monospace; letter-spacing: 0.05em; }
  `,
  template: `
    <section class="wl-container bk-page">
      @if (error(); as e) { <p class="bk-error" role="alert">{{ e }}</p> }
      @if (seat(); as s) {
        <article class="bk-card" data-testid="qr-seated">
          <h1>Welcome to table {{ s.table_label }}</h1>
          @if (s.pin) {
            <p>Friends at your table can scan the same QR code and enter this PIN to order with you.</p>
            <div class="codes">
              <div><span class="bk-muted">Order ID</span><b data-testid="qr-code">{{ s.code }}</b></div>
              <div><span class="bk-muted">PIN</span><b data-testid="qr-pin">{{ s.pin }}</b></div>
            </div>
            <p class="bk-muted">Keep these — you need them to see your bill and download the invoice later.</p>
          }
          <div class="bk-actions">
            <a routerLink="../../menu" class="wl-btn wl-btn--primary" data-testid="qr-menu">See the menu &amp; order</a>
            <a routerLink="../../session" class="wl-btn wl-btn--ghost">My table</a>
          </div>
        </article>
      } @else if (table(); as t) {
        <header class="bk-head">
          <p class="bk-muted">{{ ctx.restaurant()?.name }}{{ t.branch_name ? ' · ' + t.branch_name : '' }}</p>
          <p class="table" data-testid="qr-table">Table {{ t.table_label }}</p>
        </header>
        @if (!t.ordering_enabled) {
          <article class="bk-card"><p>Ordering from your phone isn't available here yet — please ask your waiter.</p>
            <div class="bk-actions"><a routerLink="../../menu" class="wl-btn wl-btn--primary">See the menu</a></div></article>
        } @else if (t.state === 'occupied') {
          <article class="bk-card">
            <p>This table is already open. Enter the 4-digit PIN from the person who opened it (or your waiter).</p>
            <form class="bk-row" (ngSubmit)="join()">
              <label class="bk-field"><span>Your name</span>
                <input name="name" [(ngModel)]="name" maxlength="60" required autocomplete="given-name" data-testid="qr-name" /></label>
              <label class="bk-field"><span>PIN</span>
                <input name="pin" [(ngModel)]="pin" inputmode="numeric" maxlength="4" pattern="\\d{4}" required autocomplete="off" data-testid="qr-pin-input" /></label>
              <div class="bk-actions"><button type="submit" class="wl-btn wl-btn--primary" [disabled]="busy() || pin.length !== 4 || !name.trim()" data-testid="qr-join">
                Join the table</button></div>
            </form>
          </article>
        } @else if (t.self_seating) {
          <article class="bk-card">
            <p>Order right from your phone. Your food comes to this table.</p>
            <form class="bk-row" (ngSubmit)="start()">
              <label class="bk-field"><span>Your name</span>
                <input name="name" [(ngModel)]="name" maxlength="60" required autocomplete="given-name" placeholder="e.g. Riya" data-testid="qr-name" /></label>
              <label class="bk-field"><span>Guests</span>
                <input name="party" type="number" [(ngModel)]="party" min="1" [max]="t.capacity * 2" required data-testid="qr-party" /></label>
              <div class="bk-actions"><button type="submit" class="wl-btn wl-btn--primary" [disabled]="busy() || !name.trim()" data-testid="qr-start">
                Start ordering</button></div>
            </form>
          </article>
        } @else {
          <article class="bk-card"><p>Please wait — our staff will seat you and give you an order ID and PIN.</p>
            <div class="bk-actions"><a routerLink="../../menu" class="wl-btn wl-btn--primary">See the menu</a>
              <a routerLink="../../session" class="wl-btn wl-btn--ghost">I have an order ID</a></div></article>
        }
      } @else if (!error()) {
        <div class="wl-state"><span class="wl-spinner" aria-label="Loading"></span></div>
      }
    </section>
  `,
})
export class StorefrontTableQrPage implements OnInit {
  readonly qr = input.required<string>();
  protected readonly ctx = inject(TenantContextService);
  private readonly cart = inject(CartService);
  private readonly api = inject(OrderingService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly table = signal<QrTable | null>(null);
  protected readonly seat = signal<QrSeat | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected name = '';
  protected pin = '';
  protected party = 2;

  ngOnInit(): void {
    this.name = this.cart.guestName() || this.auth.user()?.full_name || '';
    const slug = this.ctx.slug();
    if (!slug) return;
    this.api.qrTable(slug, this.qr()).subscribe({
      next: (t) => this.table.set(t),
      error: (e: ApiError) => this.error.set(e.status === 404 ? 'This QR code is no longer valid. Please ask your waiter.' : e.message),
    });
  }

  protected start(): void {
    const slug = this.ctx.slug();
    if (!slug) return;
    this.run(this.api.qrStart(slug, this.qr(), this.name.trim(), +this.party || 1));
  }

  protected join(): void {
    const slug = this.ctx.slug();
    if (!slug) return;
    this.run(this.api.qrJoin(slug, this.qr(), this.pin.trim()), true);
  }

  private run(call: ReturnType<OrderingService['qrJoin']>, goToMenu = false): void {
    this.busy.set(true);
    this.error.set(null);
    call.subscribe({
      next: (s) => {
        this.busy.set(false);
        this.cart.setPreorder(null);
        this.cart.setTableToken(s.token);
        this.cart.setGuestName(this.name);
        this.pin = '';
        if (goToMenu) void this.router.navigate(['/r', this.ctx.slug(), 'menu']);
        else this.seat.set(s);
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.code === 'RATE_LIMITED' ? 'Too many tries. Please ask your waiter for help.' : e.message);
        if (e.code === 'TABLE_OCCUPIED') this.table.update((t) => (t ? { ...t, state: 'occupied' } : t));
      },
    });
  }
}
