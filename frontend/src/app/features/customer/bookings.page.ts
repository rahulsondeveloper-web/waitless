import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import {
  BookingsService,
  MyBookings,
  QUEUE_STATUS_LABEL,
  RESERVATION_STATUS_LABEL,
  Reservation,
  formatWhen,
} from '../../core/bookings/bookings.service';
import { ApiError } from '../../core/http/api-error';
import { RealtimeService } from '../../core/realtime/realtime.service';
import { CheckoutService } from '../../core/payments/checkout.service';

const LIVE = ['pending_payment', 'confirmed', 'checked_in'];

/** Customer "My bookings": reservations and queue tokens across every restaurant. */
@Component({
  selector: 'wl-my-bookings',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './bookings.page.html',
  styleUrl: './bookings.page.scss',
})
export class MyBookingsPage implements OnInit {
  private readonly api = inject(BookingsService);
  private readonly realtime = inject(RealtimeService);
  private readonly router = inject(Router);
  private readonly checkout = inject(CheckoutService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly resLabel = RESERVATION_STATUS_LABEL;
  protected readonly queueLabel = QUEUE_STATUS_LABEL;
  protected readonly when = formatWhen;
  protected readonly data = signal<MyBookings | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);

  protected readonly upcoming = computed(() =>
    (this.data()?.reservations ?? []).filter((r) => LIVE.includes(r.status)).reverse(),
  );
  protected readonly past = computed(() => (this.data()?.reservations ?? []).filter((r) => !LIVE.includes(r.status)));
  protected readonly queue = computed(() =>
    (this.data()?.queue ?? []).filter((q) => q.status === 'waiting' || q.status === 'notified'),
  );

  ngOnInit(): void {
    this.load();
    void this.realtime.subscribeUser();
    const off = this.realtime.on<{ title: string; body: string }>('notification', (n) => {
      this.toast.set(`${n.title} — ${n.body}`);
      this.load();
    });
    this.destroyRef.onDestroy(off);
  }

  protected cancel(r: Reservation): void {
    if (!confirm(`Cancel your booking at ${r.restaurant_name} (${r.code})?`)) return;
    this.api.cancelMine(r.id).subscribe({ next: () => this.load(), error: (e: ApiError) => this.error.set(e.message) });
  }

  protected pay(r: Reservation): void {
    this.api.retryPayment(r.id).subscribe({
      next: (c) => {
        if (c.checkout.url) void this.router.navigateByUrl(c.checkout.url);
        else
          void this.checkout.open(c.checkout, { name: r.restaurant_name ?? undefined, description: `Booking ${r.code}` }).then((res) => {
            if (res === 'submitted') setTimeout(() => this.load(), 3000);
            else if (res === 'unavailable') this.error.set('The payment window could not open. Please try again.');
          });
      },
      error: (e: ApiError) => this.error.set(e.message),
    });
  }

  private load(): void {
    this.api.myBookings().subscribe({ next: (d) => this.data.set(d), error: (e: ApiError) => this.error.set(e.message) });
  }
}
