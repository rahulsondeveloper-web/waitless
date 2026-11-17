import { ChangeDetectionStrategy, Component, OnInit, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { BookingsService, MockOrder } from '../../core/bookings/bookings.service';
import { ApiError } from '../../core/http/api-error';

/**
 * Development stand-in for a payment gateway's checkout (decision D17).
 * "Pay" asks the API to send itself a *signed* webhook — the same verified path a real gateway uses.
 */
@Component({
  selector: 'wl-mock-pay',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="wl-container pay">
      <article class="wl-card card">
        <p class="tag">Test payment · no real money</p>
        @if (error(); as e) {
          <p class="err" role="alert">{{ e }}</p>
          <a routerLink="/customer/bookings" class="wl-btn wl-btn--ghost wl-btn--sm">My bookings</a>
        } @else if (order(); as o) {
          <h1>Booking fee</h1>
          <p class="amount">₹{{ o.amount }}</p>
          <p>{{ o.restaurant_name }} · ref {{ o.reservation_code }}</p>
          @if (result(); as r) {
            <p class="ok" role="status" data-testid="pay-result">
              {{ r === 'confirmed' ? 'Payment received — your table is booked!' :
                 r === 'failed' ? 'Payment failed. You can try again from your bookings.' :
                 r === 'refunded_late_payment' ? 'The booking had expired, so your payment was refunded.' :
                 'Already processed.' }}
            </p>
            <a [routerLink]="['/r', o.restaurant_slug, 'reservations']" class="wl-btn wl-btn--primary">Back to {{ o.restaurant_name }}</a>
          } @else if (o.status !== 'created') {
            <p>This payment is already {{ o.status }}.</p>
            <a routerLink="/customer/bookings" class="wl-btn wl-btn--ghost wl-btn--sm">My bookings</a>
          } @else {
            <div class="actions">
              <button type="button" class="wl-btn wl-btn--primary" [disabled]="busy()" (click)="pay(true)" data-testid="pay-success">
                Pay ₹{{ o.amount }}
              </button>
              <button type="button" class="wl-btn wl-btn--ghost" [disabled]="busy()" (click)="pay(false)">Simulate failure</button>
            </div>
          }
        } @else {
          <span class="wl-spinner" aria-label="Loading"></span>
        }
      </article>
    </section>
  `,
  styles: `
    .pay {
      display: grid;
      place-items: center;
      padding-block: 4rem;
    }
    .card {
      display: grid;
      gap: 0.8rem;
      justify-items: center;
      text-align: center;
      width: min(420px, 100%);
      padding: 2rem 1.5rem;
    }
    .tag {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      background: #fbefd3;
      color: #6b4708;
      padding: 0.2rem 0.7rem;
      border-radius: 999px;
    }
    h1 {
      font: 600 1.5rem var(--wl-font-serif);
    }
    .amount {
      font: 600 2.6rem var(--wl-font-serif);
      color: var(--wl-primary);
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      justify-content: center;
    }
    .err {
      color: #8a2a17;
    }
    .ok {
      font-weight: 600;
    }
  `,
})
export class MockPayPage implements OnInit {
  readonly orderId = input.required<string>();
  private readonly api = inject(BookingsService);
  private readonly router = inject(Router);
  protected readonly order = signal<MockOrder | null>(null);
  protected readonly result = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);

  ngOnInit(): void {
    this.api.mockOrder(this.orderId()).subscribe({
      next: (o) => this.order.set(o),
      error: (e: ApiError) => this.error.set(e.status === 404 ? 'This payment link is not valid.' : e.message),
    });
  }

  protected pay(success: boolean): void {
    this.busy.set(true);
    this.api.mockPay(this.orderId(), success).subscribe({
      next: (r) => {
        this.busy.set(false);
        this.result.set(r.result);
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}
