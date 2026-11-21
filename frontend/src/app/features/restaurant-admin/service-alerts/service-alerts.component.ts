import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { GuestServiceApi, ServiceCall } from '../../../core/ordering/guest-service.service';
import { FloorAlert, OperationsService } from '../../../core/restaurant/operations.service';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { TenancyService } from '../../../core/tenancy/tenancy.service';

const ICON: Record<string, string> = {
  water: 'water_drop',
  tissue: 'layers',
  bill: 'receipt_long',
  help: 'support_agent',
  seat: 'event_seat',
};

const FLOOR_ICON: Record<string, string> = {
  seated: 'group_add',
  seated_unchecked: 'group_add',
  left: 'logout',
  left_open: 'warning',
};

/**
 * Waiter calls from the tables, on every admin page for staff who serve tables (waiters, managers,
 * owner): a bell with the number of open calls and a card per call with "Done" once the waiter is there.
 * New calls ring softly and arrive live (Socket.IO room of each branch the person works in).
 */
@Component({
  selector: 'wl-service-alerts',
  imports: [MatButtonModule, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    :host {
      display: inline-flex;
      position: relative;
    }
    .count {
      position: absolute;
      top: 2px;
      right: 2px;
      min-width: 18px;
      height: 18px;
      padding: 0 4px;
      border-radius: 9px;
      background: #c62828;
      color: #fff;
      font: 700 0.7rem/18px sans-serif;
      text-align: center;
      pointer-events: none;
    }
    .stack {
      position: fixed;
      top: 72px;
      right: 16px;
      z-index: 1000;
      width: min(340px, calc(100vw - 32px));
      display: grid;
      gap: 8px;
    }
    .call {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 10px 12px;
      background: var(--mat-sys-surface, #fff);
      color: inherit;
      border-left: 4px solid #c62828;
      border-radius: 10px;
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);
    }
    .call mat-icon {
      color: #c62828;
    }
    .call.floor {
      border-left-color: #0a7c86;
    }
    .call.floor mat-icon {
      color: #0a7c86;
    }
    .call.floor.warn {
      border-left-color: #b26a00;
    }
    .call.floor.warn mat-icon {
      color: #b26a00;
    }
    .call b {
      display: block;
      font-size: 1rem;
    }
    .call small {
      color: var(--mat-sys-on-surface-variant, #666);
    }
    .call .note {
      display: block;
      font-size: 0.85rem;
      font-weight: 600;
      white-space: normal;
      overflow-wrap: anywhere;
    }
    .none {
      padding: 10px 12px;
      background: var(--mat-sys-surface, #fff);
      border-radius: 10px;
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);
    }
    @keyframes ring {
      0%,
      100% {
        transform: rotate(0);
      }
      25% {
        transform: rotate(-14deg);
      }
      75% {
        transform: rotate(14deg);
      }
    }
    .ringing mat-icon {
      animation: ring 0.5s ease-in-out 3;
    }
    @media (prefers-reduced-motion: reduce) {
      .ringing mat-icon {
        animation: none;
      }
    }
  `,
  template: `
    @if (enabled()) {
      <button
        mat-icon-button
        type="button"
        (click)="show.set(!show())"
        [class.ringing]="ringing()"
        [attr.aria-label]="total() + ' waiter calls and table alerts'"
        data-testid="service-bell"
      >
        <mat-icon>{{ total() ? 'notifications_active' : 'notifications' }}</mat-icon>
      </button>
      @if (total()) {
        <span class="count" data-testid="service-count">{{ total() }}</span>
      }
      @if (show() || total()) {
        <div class="stack" role="region" aria-label="Waiter calls" aria-live="polite">
          @for (a of floor(); track a.id) {
            <div class="call floor" [class.warn]="a.kind === 'left_open'" data-testid="floor-alert">
              <mat-icon aria-hidden="true">{{ floorIcon[a.kind] }}</mat-icon>
              <div>
                <b>{{ a.message }}</b>
                <small>Camera · {{ ago(a.created_at) }}</small>
              </div>
              <button
                mat-flat-button
                type="button"
                (click)="ackFloor(a)"
                [disabled]="busy() === a.id"
                data-testid="floor-ack"
              >
                OK
              </button>
            </div>
          }
          @for (c of calls(); track c.id) {
            <div class="call" data-testid="service-call">
              <mat-icon aria-hidden="true">{{ icon[c.kind] }}</mat-icon>
              <div>
                <b>{{ c.table_labels ? 'Table ' + c.table_labels : 'A table' }} · {{ c.label }}</b>
                @if (c.note) {
                  <span class="note" data-testid="service-note">{{ c.note }}</span>
                }
                <small>{{ c.guest_name ? c.guest_name + ' · ' : '' }}{{ ago(c.created_at) }}</small>
              </div>
              <button
                mat-flat-button
                type="button"
                (click)="done(c)"
                [disabled]="busy() === c.id"
                data-testid="service-done"
              >
                Done
              </button>
            </div>
          } @empty {
            @if (show() && !floor().length) {
              <div class="none">No waiter calls right now.</div>
            }
          }
        </div>
      }
    }
  `,
})
export class ServiceAlertsComponent implements OnInit {
  private readonly api = inject(GuestServiceApi);
  private readonly ops = inject(OperationsService);
  private readonly auth = inject(AuthService);
  private readonly tenancy = inject(TenancyService);
  private readonly realtime = inject(RealtimeService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly icon = ICON;
  protected readonly floorIcon = FLOOR_ICON;
  protected readonly enabled = computed(() => this.auth.hasPermission('tables.operate'));
  protected readonly calls = signal<ServiceCall[]>([]);
  protected readonly floor = signal<FloorAlert[]>([]);
  protected readonly total = computed(() => this.calls().length + this.floor().length);
  protected readonly show = signal(false);
  protected readonly busy = signal<string | null>(null);
  protected readonly ringing = signal(false);
  private readonly now = signal(Date.now());
  private branches: string[] = [];

  ngOnInit(): void {
    if (!this.enabled()) return;
    const tick = setInterval(() => this.now.set(Date.now()), 30_000);
    const offNew = this.realtime.on<ServiceCall>('service.requested', (c) => {
      if (!this.branches.includes(c.branch_id) || this.calls().some((x) => x.id === c.id)) return;
      this.calls.update((list) => [...list, c]);
      this.ring();
    });
    // Camera alerts: ones addressed to me arrive in my own room, ones for the whole branch in the branch room.
    void this.realtime.subscribeUser();
    const offFloor = this.realtime.on<FloorAlert>('floor.alert', (a) => {
      if (this.floor().some((x) => x.id === a.id)) return;
      this.floor.update((list) => [...list, a]);
      this.ring();
    });
    const offFloorAck = this.realtime.on<{ id: string }>('floor.alert.ack', (a) =>
      this.floor.update((list) => list.filter((x) => x.id !== a.id)),
    );
    const offDone = this.realtime.on<{ id: string }>('service.done', (c) =>
      this.calls.update((list) => list.filter((x) => x.id !== c.id)),
    );
    this.destroyRef.onDestroy(() => {
      clearInterval(tick);
      offNew();
      offDone();
      offFloor();
      offFloorAck();
      this.realtime.unsubscribeUser();
      for (const b of this.branches) this.realtime.unsubscribeBranch(b);
    });
    this.tenancy.restaurantMe().subscribe({
      next: (me) => {
        for (const b of me.branches.filter((x) => x.is_active)) {
          void this.realtime.subscribeBranch(b.id).then((ok) => {
            if (!ok) return; // not one of my branches
            this.branches.push(b.id);
            this.ops.floorAlerts(b.id).subscribe({
              next: (list) =>
                this.floor.update((cur) => [
                  ...cur,
                  ...list.filter((a) => !cur.some((x) => x.id === a.id)),
                ]),
              error: () => undefined,
            });
            this.api.openCalls(b.id).subscribe({
              next: (list) =>
                this.calls.update((cur) => [
                  ...cur,
                  ...list.filter((c) => !cur.some((x) => x.id === c.id)),
                ]),
              error: () => undefined,
            });
          });
        }
      },
      error: () => undefined,
    });
  }

  protected ago(iso: string): string {
    const min = Math.max(0, Math.floor((this.now() - Date.parse(iso)) / 60_000));
    return min < 1 ? 'just now' : `${min} min ago`;
  }

  protected ackFloor(a: FloorAlert): void {
    this.busy.set(a.id);
    this.ops.ackFloorAlert(a.id).subscribe({
      next: () => {
        this.busy.set(null);
        this.floor.update((list) => list.filter((x) => x.id !== a.id));
      },
      error: (e: ApiError) => {
        this.busy.set(null);
        if (e.status === 404) this.floor.update((list) => list.filter((x) => x.id !== a.id));
      },
    });
  }

  protected done(c: ServiceCall): void {
    this.busy.set(c.id);
    this.api.done(c.id).subscribe({
      next: () => {
        this.busy.set(null);
        this.calls.update((list) => list.filter((x) => x.id !== c.id));
      },
      error: (e: ApiError) => {
        this.busy.set(null);
        if (e.status === 404) this.calls.update((list) => list.filter((x) => x.id !== c.id));
      },
    });
  }

  /** A soft two-tone chime (no audio file needed) and a short vibration on phones. */
  private ring(): void {
    this.ringing.set(true);
    setTimeout(() => this.ringing.set(false), 1600);
    try {
      navigator.vibrate?.([120, 60, 120]);
      const Ctx =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctx) return;
      const ac = new Ctx();
      [880, 660].forEach((freq, i) => {
        const o = ac.createOscillator();
        const g = ac.createGain();
        o.frequency.value = freq;
        g.gain.setValueAtTime(0.0001, ac.currentTime + i * 0.22);
        g.gain.exponentialRampToValueAtTime(0.2, ac.currentTime + i * 0.22 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + i * 0.22 + 0.2);
        o.connect(g).connect(ac.destination);
        o.start(ac.currentTime + i * 0.22);
        o.stop(ac.currentTime + i * 0.22 + 0.22);
      });
      setTimeout(() => void ac.close(), 800);
    } catch {
      // sound is a nice-to-have; browsers may block it until the page was clicked once
    }
  }
}
