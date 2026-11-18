import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../../core/auth/auth.service';
import { BookingsService, Reservation, formatWhen } from '../../../core/bookings/bookings.service';
import { ApiError } from '../../../core/http/api-error';
import { CartLine, CartService } from '../../../core/ordering/cart.service';
import { Order, OrderingService, newIdempotencyKey } from '../../../core/ordering/ordering.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';

/**
 * Cart & checkout (PRD §13). Where the order goes:
 *  - the guest's table (after "Have an order ID?" code + PIN), or
 *  - a paid booking as a pre-order (PRD §12; free bookings cannot pre-order).
 */
@Component({
  selector: 'wl-storefront-cart',
  imports: [FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './cart.page.html',
  styleUrls: ['../booking-shared.scss', './cart.page.scss'],
})
export class StorefrontCartPage implements OnInit {
  protected readonly ctx = inject(TenantContextService);
  protected readonly cart = inject(CartService);
  protected readonly auth = inject(AuthService);
  private readonly api = inject(OrderingService);
  private readonly bookings = inject(BookingsService);
  private readonly router = inject(Router);

  protected readonly when = formatWhen;
  protected readonly paidBookings = signal<Reservation[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly placed = signal<Order | null>(null);
  protected notes = '';
  /** Same key for retries of one checkout → the server never creates the order twice. */
  private attemptKey: string | null = null;

  protected readonly target = computed<'table' | 'preorder' | 'none'>(() =>
    this.cart.tableToken() ? 'table' : this.cart.preorderFor() ? 'preorder' : 'none',
  );
  protected readonly preorderBooking = computed(() =>
    this.paidBookings().find((r) => r.id === this.cart.preorderFor()) ?? null,
  );

  /** "Table T3" for the Checkout card's table line. */
  protected readonly tableLabel = signal<string | null>(null);

  ngOnInit(): void {
    const token = this.cart.tableToken();
    if (token) {
      this.api.tableView(token).subscribe({
        next: (v) => this.tableLabel.set(v.table_labels.length ? `Table ${v.table_labels.join(', ')}` : v.branch_name),
        error: () => undefined,
      });
    }
    const slug = this.ctx.slug();
    if (!this.auth.isAuthenticated() || !slug) return;
    this.bookings.myBookings().subscribe({
      next: (m) =>
        this.paidBookings.set(
          m.reservations.filter((r) => r.restaurant_slug === slug && r.can_preorder && r.status === 'confirmed'),
        ),
      error: () => undefined,
    });
  }

  protected price(v: string | number): string {
    return formatPrice(v, this.ctx.restaurant()?.currency ?? 'INR');
  }

  protected setQty(l: CartLine, q: number): void {
    this.cart.setQuantity(l.key, q);
    this.attemptKey = null; // a changed cart is a new order
  }

  protected chooseBooking(id: string): void {
    this.cart.setTableToken(null);
    this.cart.setPreorder(id);
  }

  protected signIn(): void {
    void this.router.navigate(['/login'], { queryParams: { returnUrl: `/r/${this.ctx.slug()}/cart` } });
  }

  /** The name shown with these dishes: typed here, or the signed-in account name. */
  protected name(): string {
    return this.cart.guestName() || this.auth.user()?.full_name || '';
  }

  protected setName(v: string): void {
    this.cart.setGuestName(v);
  }

  protected place(): void {
    if (this.target() === 'table' && !this.name().trim()) {
      this.error.set('Tell us your name, so your dishes reach you.');
      return;
    }
    if (!this.cart.count()) return;
    this.attemptKey ??= newIdempotencyKey();
    const items = this.cart.toOrder();
    const token = this.cart.tableToken();
    const pre = this.cart.preorderFor();
    const req = token
      ? this.api.tableOrder(token, items, this.notes.trim(), this.attemptKey, this.name())
      : pre
        ? this.api.preorder(pre, items, this.notes.trim(), this.attemptKey)
        : null;
    if (!req) return;
    this.busy.set(true);
    this.error.set(null);
    req.subscribe({
      next: (o) => {
        this.busy.set(false);
        this.attemptKey = null;
        this.cart.clear();
        this.notes = '';
        if (token) void this.router.navigate(['/r', this.ctx.slug(), 'session']);
        else this.placed.set(o);
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        if (e.status === 401 && token) {
          this.cart.setTableToken(null);
          this.error.set('Your table link has ended. Enter the order ID and PIN again.');
        } else this.error.set(e.message);
        if (e.status >= 400 && e.status < 500) this.attemptKey = null; // fix the cart, then it is a new order
      },
    });
  }
}
