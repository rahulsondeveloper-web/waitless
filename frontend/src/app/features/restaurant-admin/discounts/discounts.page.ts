import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import {
  DiscountPolicy,
  DiscountPolicyService,
  ORDER_TYPE_LABEL,
  OrderType,
  discountPct,
  promiseText,
} from '../../../core/ordering/sla';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

const TYPES: OrderType[] = ['walk_in', 'booking', 'staff', 'paid_preorder'];

/**
 * Discount Settings (PRD §14): the serving-time promise and the automatic delay discount.
 * Saving affects new timers only — running and past orders keep the policy copied when they started.
 */
@Component({
  selector: 'wl-discounts-page',
  imports: [FormsModule, MatButtonModule, MatSlideToggleModule, LoadingStateComponent, ErrorStateComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './discounts.page.html',
  styleUrls: ['../admin-bookings.scss', './discounts.page.scss'],
})
export class DiscountsPage implements OnInit {
  private readonly api = inject(DiscountPolicyService);
  private readonly auth = inject(AuthService);
  private readonly snack = inject(MatSnackBar);

  protected readonly types = TYPES;
  protected readonly typeLabel = ORDER_TYPE_LABEL;
  protected readonly policy = signal<DiscountPolicy | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly saveError = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly canEdit = computed(() => this.auth.hasPermission('discounts.policy.manage'));

  protected readonly summary = computed(() => {
    const p = this.policy();
    return p ? promiseText(p) : '';
  });

  /** "Served after … → discount" rows, so owners see exactly what guests will get. */
  protected readonly preview = computed(() => {
    const p = this.policy();
    if (!p || !(p.serving_minutes > 0) || !(p.interval_minutes > 0)) return [];
    const s = p.serving_minutes;
    const i = p.interval_minutes;
    const rows: { when: string; pct: number }[] = [{ when: `Up to ${s} min`, pct: 0 }];
    for (let k = 0; k < 12; k++) {
      const from = s + k * i;
      const pct = discountPct((from + i) * 60_000, p);
      rows.push({ when: `${from}–${from + i} min`, pct });
      if (pct >= +p.max_pct) {
        rows[rows.length - 1].when = `More than ${from} min`;
        break;
      }
    }
    return rows;
  });

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.error.set(null);
    this.api.get().subscribe({ next: (p) => this.policy.set(p), error: (e: ApiError) => this.error.set(e) });
  }

  protected patch<K extends keyof DiscountPolicy>(key: K, value: DiscountPolicy[K]): void {
    const p = this.policy();
    if (p) this.policy.set({ ...p, [key]: value });
  }

  protected toggleType(t: OrderType, on: boolean): void {
    const p = this.policy();
    if (!p) return;
    const set = new Set(p.eligible_order_types);
    if (on) set.add(t);
    else set.delete(t);
    this.patch('eligible_order_types', TYPES.filter((x) => set.has(x)));
  }

  protected resetDefaults(): void {
    const p = this.policy();
    if (!p) return;
    this.policy.set({
      ...p,
      is_active: true,
      serving_minutes: 15,
      initial_pct: '2',
      interval_minutes: 5,
      increment_pct: '2',
      max_pct: '20',
      eligible_order_types: [...TYPES],
      base: 'food_subtotal',
    });
  }

  protected save(): void {
    const p = this.policy();
    if (!p) return;
    this.busy.set(true);
    this.saveError.set(null);
    const body: DiscountPolicy = {
      ...p,
      serving_minutes: +p.serving_minutes,
      interval_minutes: +p.interval_minutes,
      initial_pct: String(p.initial_pct),
      increment_pct: String(p.increment_pct),
      max_pct: String(p.max_pct),
    };
    this.api.save(body).subscribe({
      next: (saved) => {
        this.busy.set(false);
        this.policy.set(saved);
        this.snack.open('Saved. New orders use this policy; running orders keep theirs.', undefined, { duration: 4000 });
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        this.saveError.set(e.message);
      },
    });
  }
}
