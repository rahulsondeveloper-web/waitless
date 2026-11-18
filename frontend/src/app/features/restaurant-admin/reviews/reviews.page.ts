import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { GuestServiceApi, Review, ReviewSummary } from '../../../core/ordering/guest-service.service';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/** Guests' ratings and reviews after paying; the owner can hide one from the public restaurant page. */
@Component({
  selector: 'wl-reviews-page',
  imports: [DatePipe, MatButtonModule, MatIconModule, LoadingStateComponent, ErrorStateComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    .page-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 1rem; margin-bottom: 1rem; }
    .page-head h1 { margin: 0; }
    .muted { color: var(--mat-sys-on-surface-variant, #666); margin: 0.2rem 0 0; }
    .avg { display: flex; align-items: baseline; gap: 0.5rem; }
    .avg b { font-size: 2rem; }
    .stars { color: #e0a53b; letter-spacing: 0.05em; }
    .list { display: grid; gap: 0.7rem; margin: 0; padding: 0; list-style: none; }
    .rev { display: grid; grid-template-columns: 1fr auto; gap: 0.3rem 1rem; padding: 0.9rem 1rem; border: 1px solid var(--wl-line);
      border-radius: 12px; background: #fff; }
    .rev.off { opacity: 0.55; }
    .rev p { margin: 0; grid-column: 1; }
    .rev small { color: var(--mat-sys-on-surface-variant, #666); }
    .rev button { grid-row: 1 / span 3; grid-column: 2; align-self: center; }
    .tag { font-size: 0.75rem; font-weight: 600; padding: 0 0.45rem; border-radius: 999px; background: #eee; margin-left: 0.4rem; }
  `,
  template: `
    <header class="page-head">
      <div>
        <h1>Reviews</h1>
        <p class="muted">Guests rate their visit after paying. Hidden reviews stay here but leave your restaurant page.</p>
      </div>
      @if (data(); as d) {
        @if (d.count) {
          <div class="avg" data-testid="reviews-average">
            <span class="stars" aria-hidden="true">{{ stars(d.average ?? 0) }}</span>
            <b>{{ d.average }}</b><span class="muted">from {{ d.count }} shown</span>
          </div>
        }
      }
    </header>
    @if (error(); as e) {
      <wl-error-state title="Could not load reviews" [message]="e.message" (retry)="load()" />
    } @else if (!data()) {
      <wl-loading-state />
    } @else if (!data()!.reviews.length) {
      <wl-empty-state icon="reviews" title="No reviews yet" message="Guests can rate their visit after paying their bill." />
    } @else {
      <ul class="list">
        @for (r of data()!.reviews; track r.id) {
          <li class="rev" [class.off]="r.hidden" data-testid="review-row">
            <p><span class="stars" [attr.aria-label]="r.rating + ' of 5 stars'">{{ stars(r.rating) }}</span>
              @if (r.hidden) { <span class="tag">hidden</span> }</p>
            @if (r.comment) { <p>“{{ r.comment }}”</p> }
            <small>{{ r.guest_name }} · {{ r.created_at | date: 'd MMM y, HH:mm' }}</small>
            @if (canManage()) {
              <button mat-button type="button" (click)="toggle(r)" [disabled]="busy() === r.id" data-testid="review-toggle">
                <mat-icon>{{ r.hidden ? 'visibility' : 'visibility_off' }}</mat-icon>{{ r.hidden ? 'Show' : 'Hide' }}</button>
            }
          </li>
        }
      </ul>
    }
  `,
})
export class ReviewsPage implements OnInit {
  private readonly api = inject(GuestServiceApi);
  private readonly auth = inject(AuthService);
  private readonly snack = inject(MatSnackBar);
  protected readonly data = signal<ReviewSummary | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busy = signal<string | null>(null);
  protected readonly canManage = computed(() => this.auth.hasPermission('restaurant.profile.manage'));

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.error.set(null);
    this.api.staffReviews().subscribe({ next: (d) => this.data.set(d), error: (e: ApiError) => this.error.set(e) });
  }

  protected stars(n: number): string {
    const full = Math.round(n);
    return '★'.repeat(full) + '☆'.repeat(Math.max(0, 5 - full));
  }

  protected toggle(r: Review): void {
    this.busy.set(r.id);
    this.api.setHidden(r.id, !r.hidden).subscribe({
      next: () => {
        this.busy.set(null);
        this.snack.open(r.hidden ? 'Review shown on your page.' : 'Review hidden from your page.', undefined, { duration: 2500 });
        this.load();
      },
      error: (e: ApiError) => {
        this.busy.set(null);
        this.snack.open(e.message, 'OK', { duration: 5000 });
      },
    });
  }
}
