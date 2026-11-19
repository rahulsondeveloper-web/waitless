import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { SeatedNow } from '../../../core/bookings/bookings.service';
import { CartService } from '../../../core/ordering/cart.service';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';

/** The guest's phone now orders for the table they were seated at (same as scanning a free table's QR). */
export function takeSeat(cart: CartService, seated: SeatedNow, name: string): void {
  cart.setPreorder(null);
  cart.setTableToken(seated.token);
  cart.setGuestName(name);
}

/** "Go to table T3" after "Join the queue" found a free table: order ID + PIN, chairs note, menu link. */
@Component({
  selector: 'wl-seated-now',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    :host { display: grid; gap: 0.75rem; }
    h2 { margin: 0; }
    p { margin: 0; }
    .table { font-size: 2.2rem; font-weight: 700; line-height: 1.1; }
    .codes { display: flex; gap: 1.5rem; flex-wrap: wrap; }
    .codes span { display: block; font-size: 0.8rem; color: var(--wl-muted); }
    .codes b { display: block; font: 700 1.5rem ui-monospace, monospace; letter-spacing: 0.05em; }
    .chairs { display: flex; gap: 0.4rem; align-items: center; padding: 0.6rem 0.75rem; border-radius: 10px;
      background: color-mix(in srgb, var(--wl-primary) 10%, transparent); font-weight: 600; }
    .muted { font-size: 0.85rem; color: var(--wl-muted); }
    .actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  `,
  template: `
    @let s = seated();
    <h2>A table is free — no waiting!</h2>
    <p>Please go to</p>
    <p class="table" data-testid="seated-table">Table {{ s.table_label }}</p>
    @if (s.extra_chairs) {
      <p class="chairs" data-testid="seated-chairs">
        <span class="material-symbols-outlined" aria-hidden="true">event_seat</span>
        It seats {{ s.capacity }} — our waiter is bringing {{ s.extra_chairs }} more
        {{ s.extra_chairs === 1 ? 'chair' : 'chairs' }}.
      </p>
    } @else {
      <p class="muted">Our waiter knows you are coming.</p>
    }
    <div class="codes">
      <div><span>Order ID</span><b data-testid="seated-code">{{ s.code }}</b></div>
      <div><span>PIN</span><b data-testid="seated-pin">{{ s.pin }}</b></div>
    </div>
    <p class="muted">Friends at your table enter these under “Have an order ID?” to order with you. Keep them for the bill.</p>
    <div class="actions">
      <a [routerLink]="['/r', ctx.slug(), 'menu']" class="wl-btn wl-btn--primary" data-testid="seated-menu">See the menu &amp; order</a>
      <a [routerLink]="['/r', ctx.slug(), 'session']" class="wl-btn wl-btn--ghost">My table</a>
    </div>
  `,
})
export class SeatedNowComponent {
  readonly seated = input.required<SeatedNow>();
  protected readonly ctx = inject(TenantContextService);
}
