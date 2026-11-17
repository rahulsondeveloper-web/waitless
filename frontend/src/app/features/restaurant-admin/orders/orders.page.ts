import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { filter } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { formatWhen } from '../../../core/bookings/bookings.service';
import { ApiError } from '../../../core/http/api-error';
import { ORDER_STATUS_LABEL, Order, OrderingService } from '../../../core/ordering/ordering.service';
import { BoardTable, OperationsService } from '../../../core/restaurant/operations.service';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { NewOrderData, NewOrderDialogComponent } from './new-order-dialog.component';

/** Orders (PRD §13): today's orders, waiter ordering for a table, mark served, cancel with reason. */
@Component({
  selector: 'wl-orders-page',
  imports: [MatButtonModule, MatIconModule, MatMenuModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './orders.page.html',
  styleUrls: ['../admin-bookings.scss', './orders.page.scss'],
})
export class OrdersPage implements OnInit {
  private readonly api = inject(OrderingService);
  private readonly ops = inject(OperationsService);
  private readonly tenancy = inject(TenancyService);
  private readonly realtime = inject(RealtimeService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly auth = inject(AuthService);

  protected readonly label = ORDER_STATUS_LABEL;
  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly orders = signal<Order[] | null>(null);
  protected readonly tables = signal<BoardTable[]>([]);
  protected readonly showAll = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busy = signal<string | null>(null);
  protected readonly live = signal(false);
  protected readonly canCreate = computed(() => this.auth.hasPermission('orders.create'));
  protected readonly canServe = computed(() => this.auth.hasPermission('orders.mark_served'));
  protected readonly canCancel = computed(() => this.auth.hasPermission('orders.cancel'));
  protected readonly seated = computed(() => this.tables().filter((t) => !!t.session));
  protected readonly totals = computed(() => {
    const live = (this.orders() ?? []).filter((o) => o.status !== 'cancelled');
    return { count: live.length, amount: live.reduce((s, o) => s + +o.total, 0) };
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
    const offO = this.realtime.on<{ branch_id: string }>('orders.changed', (e) => {
      if (e.branch_id === this.branchId()) this.reload();
    });
    const offT = this.realtime.on<{ branch_id: string }>('tables.changed', (e) => {
      if (e.branch_id === this.branchId()) this.loadTables();
    });
    this.destroyRef.onDestroy(() => {
      offO();
      offT();
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

  protected toggleAll(all: boolean): void {
    this.showAll.set(all);
    this.reload();
  }

  protected reload(): void {
    const id = this.branchId();
    if (!id) return;
    this.api.orders(id, !this.showAll()).subscribe({
      next: (o) => this.orders.set(this.showAll() ? o : [...o].reverse()),
      error: (e: ApiError) => this.error.set(e),
    });
    this.loadTables();
  }

  protected price(v: string | number): string {
    return formatPrice(v);
  }

  protected time(iso: string): string {
    return formatWhen(iso, this.branches().find((b) => b.id === this.branchId())?.timezone);
  }

  protected where(o: Order): string {
    if (o.table_labels.length) return `Table ${o.table_labels.join(', ')}`;
    if (o.reservation_code) return `Pre-order · ${o.reservation_code}`;
    return '';
  }

  protected newOrder(tableId?: string): void {
    const id = this.branchId();
    if (!id) return;
    const data: NewOrderData = {
      branchId: id,
      timezone: this.branches().find((b) => b.id === id)?.timezone ?? 'Asia/Kolkata',
      tables: this.seated(),
      tableId,
    };
    this.dialog
      .open<NewOrderDialogComponent, NewOrderData, Order>(NewOrderDialogComponent, { data, width: '640px' })
      .afterClosed()
      .pipe(filter((o): o is Order => !!o))
      .subscribe((o) => {
        this.snack.open(`Order #${o.number} sent · order ID ${o.session_code}`, undefined, { duration: 4000 });
        this.reload();
      });
  }

  protected serve(o: Order): void {
    this.run(o.id, () => this.api.setStatus(o.id, 'served'));
  }

  protected cancel(o: Order): void {
    const reason = prompt(`Why cancel order #${o.number}?`, '');
    if (reason === null) return;
    this.run(o.id, () => this.api.cancel(o.id, reason));
  }

  private loadTables(): void {
    const id = this.branchId();
    if (!id) return;
    this.ops.board(id).subscribe({ next: (b) => this.tables.set(b.tables), error: () => undefined });
  }

  private run(key: string, call: () => ReturnType<OrderingService['setStatus']>): void {
    this.busy.set(key);
    call().subscribe({
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
