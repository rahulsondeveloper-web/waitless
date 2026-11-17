import { ChangeDetectionStrategy, Component, DestroyRef, Injectable, computed, inject, input, signal } from '@angular/core';

import { Order } from '../../../core/ordering/ordering.service';
import { clock, slaPct } from '../../../core/ordering/sla';
import { formatPrice } from '../../../core/storefront/storefront.models';

/** One 1-second clock for every timer on the page (no per-timer intervals). */
@Injectable({ providedIn: 'root' })
export class SecondTicker {
  readonly now = signal(Date.now());
  private users = 0;
  private handle: ReturnType<typeof setInterval> | null = null;

  use(destroyRef: DestroyRef): void {
    if (this.users++ === 0) this.handle = setInterval(() => this.now.set(Date.now()), 1000);
    destroyRef.onDestroy(() => {
      if (--this.users === 0 && this.handle) {
        clearInterval(this.handle);
        this.handle = null;
      }
    });
  }
}

type Tone = 'ok' | 'soon' | 'late' | 'done' | 'off';

/**
 * Serving timer (PRD §14): "12:40 left to serve" → "Running late · 2% off" → "Served in 18 min".
 * Counts down locally; `offsetMs` (server time − browser time) corrects a wrong device clock.
 * The discount shown follows the policy copied onto the order; the server stays authoritative.
 */
@Component({
  selector: 'wl-serving-timer',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (state(); as s) {
      <span class="timer" [attr.data-tone]="s.tone" [class.compact]="compact()" data-testid="serving-timer"
            [attr.aria-label]="s.label + (s.extra ? ', ' + s.extra : '')">
        <span class="dot" aria-hidden="true"></span>
        <span class="main">{{ s.label }}</span>
        @if (s.extra) { <span class="extra" data-testid="timer-discount">· {{ s.extra }}</span> }
      </span>
    }
  `,
  styles: `
    .timer {
      --tone: #2e8b57;
      display: inline-flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.35rem;
      padding: 0.3rem 0.65rem;
      border-radius: 999px;
      font-size: 0.85rem;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
      color: var(--tone);
      background: color-mix(in srgb, var(--tone) 14%, transparent);
      border: 1px solid color-mix(in srgb, var(--tone) 30%, transparent);
      justify-self: start;
    }
    .compact { padding: 0.15rem 0.5rem; font-size: 0.78rem; }
    .dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; background: currentColor; }
    .extra { font-weight: 700; }
    [data-tone='soon'] { --tone: #b7791f; }
    [data-tone='late'] { --tone: #d0452b; }
    [data-tone='late'] .dot { animation: pulse 1.2s ease-in-out infinite; }
    [data-tone='done'] { --tone: #5b6573; }
    [data-tone='done'] .dot, [data-tone='off'] .dot { display: none; }
    [data-tone='off'] { color: var(--wl-muted, #667); background: none; border: 0; padding-left: 0; font-weight: 500; }
    @keyframes pulse { 50% { opacity: 0.25; } }
    @media (prefers-reduced-motion: reduce) { [data-tone='late'] .dot { animation: none; } }
  `,
})
export class ServingTimerComponent {
  readonly order = input.required<Order>();
  readonly offsetMs = input(0);
  readonly compact = input(false);
  readonly currency = input('INR');

  private readonly ticker = inject(SecondTicker);

  constructor() {
    this.ticker.use(inject(DestroyRef));
  }

  protected readonly state = computed<{ tone: Tone; label: string; extra: string } | null>(() => {
    const o = this.order();
    const sla = o.sla;
    if (o.status === 'cancelled') return null;
    if (!sla) {
      if (o.order_type === 'paid_preorder' && !o.table_session_id) {
        return { tone: 'off', label: 'Timer starts when you arrive', extra: '' };
      }
      return o.status === 'placed' ? { tone: 'off', label: 'Timer starts when the kitchen accepts', extra: '' } : null;
    }
    const now = this.ticker.now() + this.offsetMs();
    const start = Date.parse(sla.started_at);
    const deadline = Date.parse(sla.deadline_at);
    const pct = slaPct(sla, now);
    const off = pct > 0 ? `${+pct.toFixed(2)}% off${this.amount(o, pct)}` : '';
    if (sla.status === 'served') {
      const took = Math.round((Date.parse(sla.ended_at ?? sla.deadline_at) - start) / 60_000);
      return { tone: 'done', label: `Served in ${took} min`, extra: off };
    }
    if (sla.status !== 'running') return null;
    if (now <= deadline) {
      const left = deadline - now;
      return { tone: left <= 3 * 60_000 ? 'soon' : 'ok', label: `${clock(left)} left to serve`, extra: '' };
    }
    const late = `Running late · ${clock(now - deadline)}`;
    return { tone: 'late', label: late, extra: sla.eligible ? off : '' };
  });

  private amount(o: Order, pct: number): string {
    if (this.compact()) return '';
    const sla = o.sla!;
    const base = sla.base === 'order_total' ? +o.total : +o.subtotal;
    return ` (${formatPrice(Math.round(base * pct) / 100, this.currency())})`;
  }
}
