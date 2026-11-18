import { ChangeDetectionStrategy, Component, OnInit, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiError } from '../../../core/http/api-error';
import { GuestServiceApi, Review } from '../../../core/ordering/guest-service.service';

/** Rate the visit after paying: 1–5 stars and a comment, once per visit (table token). */
@Component({
  selector: 'wl-review-form',
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    :host { display: block; }
    .box { display: grid; gap: 0.6rem; text-align: left; width: 100%; }
    h3 { margin: 0; font-family: var(--wl-font-serif); font-size: 1.35rem; }
    .stars { display: flex; gap: 0.15rem; }
    .star { border: 0; background: none; padding: 0.1rem; cursor: pointer; font-size: 2rem; line-height: 1; color: var(--wl-line); }
    .star.on { color: #e0a53b; }
    .star:focus-visible { outline: 2px solid var(--wl-primary); border-radius: 6px; }
    textarea { width: 100%; padding: 0.7rem 0.85rem; border: 1px solid var(--wl-line); border-radius: 10px; font: inherit; resize: vertical; }
    .done { margin: 0; color: #2e7d4f; font-weight: 600; }
    .err { margin: 0; color: #a3321c; font-size: 0.85rem; }
    .muted { margin: 0; color: var(--wl-muted); font-size: 0.85rem; }
  `,
  template: `
    @if (sent(); as r) {
      <div class="box" data-testid="review-sent">
        <h3>Thank you for your review!</h3>
        <div class="stars" [attr.aria-label]="r.rating + ' of 5 stars'">
          @for (n of five; track n) { <span class="star" [class.on]="n <= r.rating" aria-hidden="true">★</span> }
        </div>
        @if (r.comment) { <p class="muted">“{{ r.comment }}”</p> }
      </div>
    } @else if (allowed()) {
      <form class="box" (ngSubmit)="submit()" data-testid="review-form">
        <h3>How was your meal?</h3>
        <div class="stars" role="radiogroup" aria-label="Your rating">
          @for (n of five; track n) {
            <button type="button" class="star" role="radio" [class.on]="n <= (hover() || rating())" [attr.aria-checked]="rating() === n"
                    [attr.aria-label]="n + (n === 1 ? ' star' : ' stars')" (click)="rating.set(n)"
                    (mouseenter)="hover.set(n)" (mouseleave)="hover.set(0)" [attr.data-testid]="'star-' + n">★</button>
          }
        </div>
        <textarea name="comment" [(ngModel)]="comment" rows="3" maxlength="1000"
                  placeholder="Tell others what you liked (optional)" data-testid="review-comment"></textarea>
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
        <div><button type="submit" class="wl-btn wl-btn--primary" [disabled]="!rating() || busy()" data-testid="review-submit">Send review</button></div>
      </form>
    }
  `,
})
export class ReviewFormComponent implements OnInit {
  readonly token = input.required<string>();
  readonly guestName = input('');
  private readonly api = inject(GuestServiceApi);

  protected readonly five = [1, 2, 3, 4, 5];
  protected readonly rating = signal(0);
  protected readonly hover = signal(0);
  protected readonly allowed = signal(false);
  protected readonly sent = signal<Review | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected comment = '';

  ngOnInit(): void {
    this.api.myReview(this.token()).subscribe({
      next: (r) => {
        this.allowed.set(r.can_review);
        if (r.review) this.sent.set(r.review);
      },
      error: () => this.allowed.set(false),
    });
  }

  protected submit(): void {
    if (!this.rating()) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.review(this.token(), this.rating(), this.comment.trim(), this.guestName()).subscribe({
      next: (r) => {
        this.busy.set(false);
        this.sent.set(r);
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}
