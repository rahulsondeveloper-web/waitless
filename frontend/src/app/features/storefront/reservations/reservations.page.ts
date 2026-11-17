import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../../core/auth/auth.service';
import {
  Availability,
  BookingOptions,
  BookingsService,
  Checkout,
  RESERVATION_STATUS_LABEL,
  Reservation,
  ReservationType,
  Slot,
  formatWhen,
  localDate,
} from '../../../core/bookings/bookings.service';
import { ApiError } from '../../../core/http/api-error';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';

/**
 * Table booking (PRD §12): date & party → time slot → free or paid → sign in → confirm.
 * Paid bookings go to the payment checkout; the booking is confirmed only by the server's verified webhook.
 */
@Component({
  selector: 'wl-storefront-reservations',
  imports: [FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './reservations.page.html',
  styleUrl: './reservations.page.scss',
})
export class StorefrontReservationsPage implements OnInit {
  protected readonly ctx = inject(TenantContextService);
  protected readonly auth = inject(AuthService);
  private readonly api = inject(BookingsService);
  private readonly router = inject(Router);

  protected readonly statusLabel = RESERVATION_STATUS_LABEL;
  protected readonly when = formatWhen;
  protected readonly options = signal<BookingOptions[]>([]);
  protected readonly loaded = signal(false);
  protected readonly branchId = signal<string | null>(null);
  protected readonly date = signal('');
  protected readonly party = signal(2);
  protected readonly availability = signal<Availability | null>(null);
  protected readonly loadingSlots = signal(false);
  protected readonly slot = signal<Slot | null>(null);
  protected readonly type = signal<ReservationType>('free');
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly booked = signal<Reservation | null>(null);
  protected readonly mine = signal<Reservation[]>([]);
  protected name = '';
  protected notes = '';

  protected readonly bookable = computed(() => this.options().filter((o) => o.accepts_reservations));
  protected readonly branch = computed(() => this.options().find((o) => o.branch_id === this.branchId()) ?? null);
  protected readonly tz = computed(
    () => this.ctx.restaurant()?.branches.find((b) => b.id === this.branchId())?.timezone ?? 'Asia/Kolkata',
  );
  protected readonly minDate = computed(() => localDate(this.tz()));
  protected readonly maxDate = computed(() => {
    const days = this.branch()?.max_advance_days ?? 30;
    return localDate(this.tz(), new Date(Date.now() + days * 86_400_000));
  });
  protected readonly upcoming = computed(() =>
    this.mine().filter((r) => ['pending_payment', 'confirmed', 'checked_in'].includes(r.status)),
  );

  ngOnInit(): void {
    const slug = this.ctx.slug();
    if (!slug) return;
    this.name = this.auth.user()?.full_name ?? '';
    this.api.options(slug).subscribe({
      next: (opts) => {
        this.options.set(opts);
        const first = opts.find((o) => o.accepts_reservations);
        this.loaded.set(true);
        if (first) {
          this.branchId.set(first.branch_id);
          this.date.set(this.minDate());
          this.type.set(first.free_enabled ? 'free' : 'paid');
          this.loadSlots();
        }
      },
      error: (e: ApiError) => {
        this.error.set(e.message);
        this.loaded.set(true);
      },
    });
    this.loadMine();
  }

  protected setBranch(id: string): void {
    this.branchId.set(id);
    const b = this.branch();
    if (b) this.type.set(b.free_enabled ? 'free' : 'paid');
    this.loadSlots();
  }

  protected setDate(d: string): void {
    this.date.set(d);
    this.loadSlots();
  }

  protected setParty(n: number): void {
    this.party.set(Math.max(1, Math.floor(Number(n) || 1)));
    this.loadSlots();
  }

  protected pick(s: Slot): void {
    if (s.available) this.slot.set(s);
  }

  /** Shared/incognito windows share one sign-in: let the guest switch to their own account. */
  protected switchAccount(): void {
    this.auth.logout(`/login?returnUrl=${encodeURIComponent(`/r/${this.ctx.slug()}/reservations`)}`);
  }

  protected signIn(): void {
    void this.router.navigate(['/login'], { queryParams: { returnUrl: `/r/${this.ctx.slug()}/reservations` } });
  }

  protected confirm(): void {
    const slug = this.ctx.slug();
    const branch = this.branchId();
    const slot = this.slot();
    if (!slug || !branch || !slot) return;
    this.busy.set(true);
    this.error.set(null);
    this.api
      .book(slug, {
        branch_id: branch,
        starts_at: slot.starts_at,
        party_size: this.party(),
        type: this.type(),
        guest_name: this.name.trim() || undefined,
        notes: this.notes.trim(),
      })
      .subscribe({
        next: (res) => {
          this.busy.set(false);
          if (res.payment) {
            this.openCheckout(res.payment);
            return;
          }
          this.booked.set(res.reservation);
          this.loadMine();
        },
        error: (e: ApiError) => {
          this.busy.set(false);
          this.error.set(e.message);
          if (e.code === 'SLOT_TAKEN') this.loadSlots();
        },
      });
  }

  protected pay(r: Reservation): void {
    this.api.retryPayment(r.id).subscribe({
      next: (c) => this.openCheckout(c),
      error: (e: ApiError) => this.error.set(e.message),
    });
  }

  protected cancel(r: Reservation): void {
    const note =
      r.type === 'paid'
        ? `Cancel booking ${r.code}? The fee is refunded when you cancel at least ${this.branch()?.free_cancel_hours ?? 2} hours ahead.`
        : `Cancel booking ${r.code}?`;
    if (!confirm(note)) return;
    this.api.cancelMine(r.id).subscribe({
      next: () => this.loadMine(),
      error: (e: ApiError) => this.error.set(e.message),
    });
  }

  protected another(): void {
    this.booked.set(null);
    this.slot.set(null);
    this.loadSlots();
  }

  private openCheckout(c: Checkout): void {
    if (c.checkout.url) {
      void this.router.navigateByUrl(c.checkout.url);
      return;
    }
    // Real gateways (Razorpay) open their own checkout window; the webhook confirms the booking.
    this.error.set('Online payment is opening in a new window. Your booking is confirmed once the payment succeeds.');
  }

  private loadSlots(): void {
    const slug = this.ctx.slug();
    const branch = this.branchId();
    if (!slug || !branch || !this.date()) return;
    this.slot.set(null);
    this.loadingSlots.set(true);
    this.api.availability(slug, branch, this.date(), this.party()).subscribe({
      next: (a) => {
        this.availability.set(a);
        this.loadingSlots.set(false);
      },
      error: (e: ApiError) => {
        this.availability.set(null);
        this.loadingSlots.set(false);
        this.error.set(e.message);
      },
    });
  }

  private loadMine(): void {
    const slug = this.ctx.slug();
    if (!this.auth.isAuthenticated() || !slug) return;
    this.api.myBookings().subscribe({
      next: (m) => this.mine.set(m.reservations.filter((r) => r.restaurant_slug === slug)),
      error: () => undefined,
    });
  }
}
