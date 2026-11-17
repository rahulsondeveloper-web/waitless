import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { interval } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { formatWhen } from '../../../core/bookings/bookings.service';
import { ApiError } from '../../../core/http/api-error';
import { Order, OrderingService } from '../../../core/ordering/ordering.service';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

type Lane = { key: 'placed' | 'accepted' | 'preparing' | 'ready'; title: string; next?: 'accepted' | 'preparing' | 'ready' | 'served'; action?: string };

const LANES: Lane[] = [
  { key: 'placed', title: 'New', next: 'accepted', action: 'Accept' },
  { key: 'accepted', title: 'Accepted', next: 'preparing', action: 'Start cooking' },
  { key: 'preparing', title: 'Preparing', next: 'ready', action: 'Ready' },
  { key: 'ready', title: 'Ready to serve', next: 'served', action: 'Served' },
];

/** Kitchen display (PRD §13): live tickets by status, elapsed time, pre-orders waiting for arrival. */
@Component({
  selector: 'wl-kitchen-page',
  imports: [MatButtonModule, MatIconModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './kitchen.page.html',
  styleUrls: ['../admin-bookings.scss', './kitchen.page.scss'],
})
export class KitchenPage implements OnInit {
  private readonly api = inject(OrderingService);
  private readonly tenancy = inject(TenancyService);
  private readonly realtime = inject(RealtimeService);
  private readonly snack = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(AuthService);

  protected readonly lanes = LANES;
  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly orders = signal<Order[] | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busy = signal<string | null>(null);
  protected readonly live = signal(false);
  protected readonly now = signal(Date.now());
  protected readonly canCook = computed(() => this.auth.hasPermission('kitchen.operate'));
  protected readonly canServe = computed(() => this.auth.hasPermission('orders.mark_served'));

  /** Paid pre-orders whose guests have not arrived yet: shown apart, cannot be started. */
  protected readonly waiting = computed(() =>
    (this.orders() ?? []).filter((o) => o.order_type === 'paid_preorder' && !o.table_session_id),
  );
  protected readonly byLane = computed(() => {
    const live = (this.orders() ?? []).filter((o) => !(o.order_type === 'paid_preorder' && !o.table_session_id));
    return Object.fromEntries(LANES.map((l) => [l.key, live.filter((o) => o.status === l.key)])) as Record<Lane['key'], Order[]>;
  });

  ngOnInit(): void {
    this.tenancy.restaurantMe().subscribe({
      next: (me) => {
        const active = me.branches.filter((b) => b.is_active);
        this.branches.set(active);
        const first = active.find((b) => b.is_primary) ?? active[0];
        if (first) this.selectBranch(first.id);
        else this.orders.set([]);
      },
      error: (e: ApiError) => this.error.set(e),
    });
    const off = this.realtime.on<{ branch_id: string }>('orders.changed', (e) => {
      if (e.branch_id === this.branchId()) this.reload();
    });
    interval(20_000)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.now.set(Date.now()));
    this.destroyRef.onDestroy(() => {
      off();
      const b = this.branchId();
      if (b) this.realtime.unsubscribeBranch(b);
    });
  }

  protected selectBranch(id: string): void {
    const previous = this.branchId();
    if (previous && previous !== id) this.realtime.unsubscribeBranch(previous);
    this.branchId.set(id);
    this.orders.set(null);
    this.reload();
    void this.realtime.subscribeBranch(id).then((ok) => this.live.set(ok));
  }

  protected reload(): void {
    const id = this.branchId();
    if (!id) return;
    this.api.orders(id, true).subscribe({ next: (o) => this.orders.set(o), error: (e: ApiError) => this.error.set(e) });
  }

  protected minutes(o: Order): number {
    return Math.max(0, Math.floor((this.now() - Date.parse(o.placed_at)) / 60_000));
  }

  protected where(o: Order): string {
    if (o.table_labels.length) return `Table ${o.table_labels.join(', ')}`;
    if (o.reservation_code) return `Booking ${o.reservation_code}`;
    return o.session_code ?? '';
  }

  protected when(iso: string): string {
    return formatWhen(iso);
  }

  protected allowed(lane: Lane): boolean {
    return lane.next === 'served' ? this.canServe() : this.canCook();
  }

  protected advance(o: Order, lane: Lane): void {
    if (!lane.next) return;
    this.busy.set(o.id);
    this.api.setStatus(o.id, lane.next).subscribe({
      next: () => {
        this.busy.set(null);
        this.reload();
      },
      error: (e: ApiError) => {
        this.busy.set(null);
        this.snack.open(e.message, 'Dismiss', { duration: 5000 });
        this.reload();
      },
    });
  }
}
