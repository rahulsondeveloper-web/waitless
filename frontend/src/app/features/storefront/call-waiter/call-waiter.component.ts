import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';

import { ApiError } from '../../../core/http/api-error';
import { CartService } from '../../../core/ordering/cart.service';
import { CALL_OPTIONS, CallKind, GuestServiceApi } from '../../../core/ordering/guest-service.service';
import { RealtimeService } from '../../../core/realtime/realtime.service';

/**
 * "Call waiter" for guests whose phone has joined a table (QR or order ID) — no order ID re-entry.
 * Four options; after a tap every option waits 2 minutes (the server enforces it too). Waiters and
 * managers get a live alert with the table number and clear it when they reach the table.
 */
@Component({
  selector: 'wl-call-waiter',
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    :host { position: fixed; right: 1rem; bottom: 5.5rem; z-index: 55; display: grid; justify-items: end; gap: 0.5rem; }
    .fab { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.75rem 1.1rem; border: 0; border-radius: 999px;
      background: var(--wl-text, #2b2522); color: #fff; font: 600 0.95rem var(--wl-font-sans); box-shadow: var(--wl-shadow); cursor: pointer; }
    .fab .material-symbols-outlined { font-size: 1.25rem; }
    .panel { width: min(300px, calc(100vw - 2rem)); background: var(--wl-surface, #fff); color: var(--wl-text); border: 1px solid var(--wl-line);
      border-radius: 16px; padding: 0.9rem; box-shadow: var(--wl-shadow); display: grid; gap: 0.6rem; }
    .panel h2 { margin: 0; font-size: 1rem; }
    .opts { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
    .opt { display: grid; justify-items: center; gap: 0.2rem; padding: 0.7rem 0.4rem; border: 1px solid var(--wl-line); border-radius: 12px;
      background: var(--wl-bg); color: var(--wl-text); font: 600 0.85rem var(--wl-font-sans); cursor: pointer; }
    .opt .material-symbols-outlined { font-size: 1.5rem; color: var(--wl-primary); }
    .opt:hover:not(:disabled) { border-color: var(--wl-primary); }
    .opt:disabled { opacity: 0.45; cursor: not-allowed; }
    .note { margin: 0; font-size: 0.82rem; color: var(--wl-muted); }
    .sent { margin: 0; font-size: 0.85rem; color: #2e7d4f; font-weight: 600; }
    .err { margin: 0; font-size: 0.82rem; color: #a3321c; }
  `,
  template: `
    @if (open()) {
      <div class="panel" role="dialog" aria-label="Call the waiter" data-testid="call-panel">
        <h2>What do you need?</h2>
        <div class="opts">
          @for (o of options; track o.kind) {
            <button type="button" class="opt" (click)="call(o.kind)" [disabled]="waiting() || busy()"
                    [attr.data-testid]="'call-' + o.kind">
              <span class="material-symbols-outlined" aria-hidden="true">{{ o.icon }}</span>{{ o.label }}
            </button>
          }
        </div>
        @if (sent(); as s) { <p class="sent" role="status" data-testid="call-sent">{{ s }}</p> }
        @if (waiting()) {
          <p class="note" data-testid="call-wait">You can call again in {{ countdown() }}.</p>
        } @else {
          <p class="note">A waiter comes to your table.</p>
        }
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </div>
    }
    <button type="button" class="fab" (click)="toggle()" [attr.aria-expanded]="open()" data-testid="call-waiter">
      <span class="material-symbols-outlined" aria-hidden="true">{{ open() ? 'close' : 'notifications_active' }}</span>
      {{ open() ? 'Close' : 'Call waiter' }}
    </button>
  `,
})
export class CallWaiterComponent {
  private readonly api = inject(GuestServiceApi);
  private readonly cart = inject(CartService);
  private readonly realtime = inject(RealtimeService);

  protected readonly options = CALL_OPTIONS;
  protected readonly open = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly sent = signal<string | null>(null);
  /** cooldown end in this device's clock (server time − offset) */
  private readonly until = signal<number | null>(null);
  private readonly now = signal(Date.now());
  protected readonly waiting = computed(() => (this.until() ?? 0) > this.now());
  protected readonly countdown = computed(() => {
    const left = Math.max(0, Math.ceil(((this.until() ?? 0) - this.now()) / 1000));
    return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
  });

  constructor() {
    const tick = setInterval(() => this.now.set(Date.now()), 1000);
    const off = this.realtime.on('service.done', () => this.sent.set('The waiter has seen to it. Thank you!'));
    inject(DestroyRef).onDestroy(() => {
      clearInterval(tick);
      off();
    });
    // A new table (or another device of the same table): load when the cooldown ends, and listen to the
    // table's room so "the waiter has seen to it" arrives on any page.
    let joined: string | null = null;
    effect(() => {
      const token = this.cart.tableToken();
      untracked(() => {
        if (joined && joined !== token) this.realtime.unsubscribeTableSession(joined);
        joined = token;
        this.until.set(null);
        this.sent.set(null);
        if (token) {
          void this.realtime.subscribeTableSession(token);
          this.load(token);
        }
      });
    });
    inject(DestroyRef).onDestroy(() => joined && this.realtime.unsubscribeTableSession(joined));
  }

  protected toggle(): void {
    this.open.update((v) => !v);
    this.error.set(null);
    const token = this.cart.tableToken();
    if (this.open() && token) this.load(token);
  }

  protected call(kind: CallKind): void {
    const token = this.cart.tableToken();
    if (!token || this.waiting()) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.call(token, kind, this.cart.guestName()).subscribe({
      next: (r) => {
        this.busy.set(false);
        this.setUntil(r.cooldown_until, r.server_time);
        this.sent.set(`${r.request.label} — a waiter is on the way.`);
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        if (e.code === 'CALL_COOLDOWN') this.load(token);
        this.error.set(e.message);
      },
    });
  }

  private load(token: string): void {
    this.api.calls(token).subscribe({
      next: (s) => this.setUntil(s.cooldown_until, s.server_time),
      error: () => undefined,
    });
  }

  private setUntil(until: string | null, serverTime: string): void {
    const offset = Date.parse(serverTime) - Date.now();
    this.until.set(until ? Date.parse(until) - offset : null);
    this.now.set(Date.now());
  }
}
