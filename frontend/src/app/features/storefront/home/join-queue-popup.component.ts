import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService } from '../../../core/auth/auth.service';
import { BookingsService, SeatedNow } from '../../../core/bookings/bookings.service';
import { ApiError } from '../../../core/http/api-error';
import { CartService } from '../../../core/ordering/cart.service';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { PopupComponent } from '../../../shared/ui/popup/popup.component';
import { SeatedNowComponent, takeSeat } from '../queue/seated-now.component';

/**
 * "Join the queue" asks for the number of guests first. When a free table suits the group (up to 2 more
 * guests than its seats, or 1 fewer) and nobody waiting fits it, the guest is seated at once and the waiter
 * is alerted to arrange chairs; otherwise they get a token on the queue page as before.
 */
@Component({
  selector: 'wl-join-queue-popup',
  imports: [FormsModule, PopupComponent, SeatedNowComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    p { margin: 0; }
    .muted { color: var(--wl-muted); font-size: 0.9rem; }
    .stepper { display: flex; align-items: center; gap: 0.75rem; }
    .stepper button { width: 2.75rem; height: 2.75rem; border-radius: 50%; border: 1px solid var(--wl-line);
      background: var(--wl-bg); color: var(--wl-text); font-size: 1.4rem; cursor: pointer; line-height: 1; }
    .stepper button:disabled { opacity: 0.4; cursor: not-allowed; }
    .stepper input { width: 4.5rem; text-align: center; font: 700 1.6rem var(--wl-font-sans); padding: 0.3rem;
      border: 1px solid var(--wl-line); border-radius: 10px; background: var(--wl-surface); color: inherit; }
    label { display: grid; gap: 0.3rem; font-weight: 600; font-size: 0.9rem; }
    label input[type='text'] { padding: 0.6rem 0.7rem; border: 1px solid var(--wl-line); border-radius: 10px;
      background: var(--wl-surface); color: inherit; font: inherit; font-weight: 400; }
    .free { display: flex; gap: 0.4rem; align-items: center; color: #2e7d4f; font-weight: 600; }
    .err { color: #a3321c; }
    .actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  `,
  template: `
    <wl-popup [title]="seated() ? 'Your table' : 'Join the queue'" testId="join-queue-popup" (closed)="closed.emit()">
      @if (seated(); as s) {
        <wl-seated-now [seated]="s" />
      } @else {
        <p id="jq-q"><b>How many guests?</b></p>
        <div class="stepper" role="group" aria-labelledby="jq-q">
          <button type="button" (click)="step(-1)" [disabled]="party <= 1" aria-label="One guest fewer">−</button>
          <input type="number" min="1" max="50" [(ngModel)]="party" name="party" aria-label="Number of guests" data-testid="jq-party" />
          <button type="button" (click)="step(1)" [disabled]="party >= 50" aria-label="One guest more">+</button>
        </div>
        @if (freeTables() > 0) {
          <p class="free"><span class="material-symbols-outlined" aria-hidden="true">event_available</span>
            Tables are free right now — if one suits your group, you can sit down straight away.</p>
        } @else {
          <p class="muted">We'll give you a token and tell you when your table is ready.</p>
        }
        @if (auth.user(); as u) {
          <label>Your name <input type="text" [(ngModel)]="name" name="name" maxlength="80" autocomplete="name" /></label>
          <p class="muted">Joining as {{ u.full_name }}{{ u.phone ? ' · ' + u.phone : '' }}</p>
        }
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
        <div class="actions">
          @if (auth.isAuthenticated()) {
            <button type="button" class="wl-btn wl-btn--primary" (click)="go()" [disabled]="busy() || !valid()" data-testid="jq-continue">
              Continue
            </button>
          } @else {
            <button type="button" class="wl-btn wl-btn--primary" (click)="signIn()" [disabled]="!valid()" data-testid="jq-sign-in">
              Sign in with your mobile to continue
            </button>
          }
          <button type="button" class="wl-btn wl-btn--ghost" (click)="closed.emit()">Cancel</button>
        </div>
      }
    </wl-popup>
  `,
})
export class JoinQueuePopupComponent {
  readonly branchId = input.required<string>();
  readonly freeTables = input(0);
  readonly closed = output<void>();

  protected readonly auth = inject(AuthService);
  private readonly api = inject(BookingsService);
  private readonly cart = inject(CartService);
  private readonly ctx = inject(TenantContextService);
  private readonly router = inject(Router);

  protected readonly seated = signal<SeatedNow | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected party = 2;
  protected name = this.auth.user()?.full_name ?? '';

  protected valid(): boolean {
    return Number.isInteger(+this.party) && +this.party >= 1 && +this.party <= 50;
  }

  protected step(d: number): void {
    this.party = Math.min(50, Math.max(1, (+this.party || 1) + d));
  }

  protected signIn(): void {
    void this.router.navigate(['/login'], { queryParams: { returnUrl: `/r/${this.ctx.slug()}/queue?party=${+this.party}` } });
  }

  protected go(): void {
    const slug = this.ctx.slug();
    if (!slug || !this.valid()) return;
    this.busy.set(true);
    this.error.set(null);
    const name = this.name.trim();
    this.api.joinQueue(slug, { branch_id: this.branchId(), party_size: +this.party, guest_name: name || undefined, seat_now: true }).subscribe({
      next: (e) => {
        this.busy.set(false);
        if (e.seated_now) {
          takeSeat(this.cart, e.seated_now, name || e.guest_name);
          this.seated.set(e.seated_now);
        } else {
          void this.router.navigate(['/r', slug, 'queue']); // the token, live
        }
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        if (e.code === 'ALREADY_IN_QUEUE') void this.router.navigate(['/r', slug, 'queue']);
        else this.error.set(e.message);
      },
    });
  }
}
