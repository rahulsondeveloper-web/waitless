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

type Tone = 'ok' | 'soon' | 'late' | 'done' | 'off' | 'wait';

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
      <span class="timer" [attr.data-tone]="s.tone" [class.compact]="compact()" [class.large]="large()" data-testid="serving-timer"
            [attr.aria-label]="s.label + (s.extra ? ', ' + s.extra : '')">
        <span class="dot" aria-hidden="true"></span>
        <span class="main">{{ s.label }}</span>
        @if (s.extra) { <span class="extra" data-testid="timer-discount">· {{ s.extra }}</span> }
        @if (large() && s.used !== null) {
          <span class="bar" aria-hidden="true"><span [style.width.%]="s.used"></span></span>
        }
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
    /* Kitchen screen: readable from across the kitchen */
    .large { display: grid; grid-template-columns: auto 1fr; justify-self: stretch; border-radius: 10px;
      padding: 0.45rem 0.7rem; font-size: 1.25rem; font-weight: 800; letter-spacing: 0.01em; }
    .large .dot { width: 0.75rem; height: 0.75rem; }
    .large .extra { grid-column: 1 / -1; font-size: 0.85rem; }
    .bar { grid-column: 1 / -1; height: 6px; border-radius: 3px; background: color-mix(in srgb, var(--tone) 22%, transparent); overflow: hidden; }
    .bar span { display: block; height: 100%; background: var(--tone); transition: width 1s linear; }
    .large[data-tone='late'] { color: #fff; background: #d0452b; border-color: #d0452b; }
    .large[data-tone='late'] .bar { background: rgba(255, 255, 255, 0.35); }
    .large[data-tone='late'] .bar span { background: #fff; }
    .large[data-tone='wait'] { --tone: #6b5bd2; }
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
  /** Big block with a progress bar (kitchen screen); new orders show how long they have waited. */
  readonly large = input(false);
  readonly currency = input('INR');

  private readonly ticker = inject(SecondTicker);

  constructor() {
    this.ticker.use(inject(DestroyRef));
  }

  protected readonly state = computed<{ tone: Tone; label: string; extra: string; used: number | null } | null>(() => {
    const s = this.compute();
    return s && { used: null, ...s };
  });

  private compute(): { tone: Tone; label: string; extra: string; used?: number | null } | null {
    const o = this.order();
    const sla = o.sla;
    if (o.status === 'cancelled') return null;
    const notArrived = o.order_type === 'paid_preorder' && !o.table_session_id;
    if (!sla && this.large() && o.status === 'placed' && !notArrived) {
      const waited = this.ticker.now() + this.offsetMs() - Date.parse(o.placed_at);
      return { tone: 'wait', label: `Waiting ${clock(Math.max(0, waited))}`, extra: 'Accept to start the 15-min timer' };
    }
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
    const used = Math.min(100, Math.max(0, ((now - start) / Math.max(1, deadline - start)) * 100));
    if (now <= deadline) {
      const left = deadline - now;
      return { tone: left <= 3 * 60_000 ? 'soon' : 'ok', label: `${clock(left)} left to serve`, extra: '', used };
    }
    const late = `Running late · ${clock(now - deadline)}`;
    return { tone: 'late', label: late, extra: sla.eligible ? off : '', used: 100 };
  }

  private amount(o: Order, pct: number): string {
    if (this.compact() || this.large()) return '';
    const sla = o.sla!;
    const base = sla.base === 'order_total' ? +o.total : +o.subtotal;
    return ` (${formatPrice(Math.round(base * pct) / 100, this.currency())})`;
  }
}
