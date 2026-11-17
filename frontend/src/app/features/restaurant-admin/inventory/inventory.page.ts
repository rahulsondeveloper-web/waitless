import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { forkJoin } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import {
  AlertRow,
  Alerts,
  InventoryCategory,
  InventoryItem,
  InventoryService,
  ManualType,
  REPORTS,
  Report,
  ReportKind,
  StockRow,
  Supplier,
  Transfer,
  downloadCsv,
  qty,
  toCsv,
} from '../../../core/inventory/inventory.service';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { PurchaseDialogComponent, PurchaseDialogData } from '../purchases/purchase-dialog.component';
import { HistoryDialogComponent } from './history-dialog.component';
import { ItemDialogComponent, ItemDialogData } from './item-dialog.component';
import { MovementDialogComponent, MovementDialogData } from './movement-dialog.component';
import { TransferDialogComponent, TransferDialogData } from './transfer-dialog.component';

const TRANSFER_LABEL: Record<Transfer['status'], string> = { in_transit: 'On the way', received: 'Received', cancelled: 'Cancelled' };

/** Inventory (PRD §8): stock per branch, every change with a reason, transfers, alerts and reports. */
@Component({
  selector: 'wl-inventory-page',
  imports: [
    DatePipe,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatTabsModule,
    LoadingStateComponent,
    ErrorStateComponent,
    EmptyStateComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './inventory.page.html',
  styleUrls: ['../admin-bookings.scss', './inventory-forms.scss', './inventory.page.scss'],
})
export class InventoryPage implements OnInit {
  private readonly api = inject(InventoryService);
  private readonly tenancy = inject(TenancyService);
  private readonly realtime = inject(RealtimeService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly qty = qty;
  protected readonly reports = REPORTS;
  protected readonly transferLabel = TRANSFER_LABEL;
  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly stock = signal<StockRow[] | null>(null);
  protected readonly items = signal<InventoryItem[]>([]);
  protected readonly categories = signal<InventoryCategory[]>([]);
  protected readonly suppliers = signal<Supplier[]>([]);
  protected readonly transfers = signal<Transfer[] | null>(null);
  protected readonly alerts = signal<Alerts | null>(null);
  protected readonly report = signal<Report | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly search = signal('');
  protected readonly stateFilter = signal<'all' | 'low' | 'out'>('all');
  protected reportKind: ReportKind = 'current';
  protected reportFrom = '';
  protected reportTo = '';

  protected readonly canAdjust = computed(() => this.auth.hasPermission('inventory.adjust'));
  protected readonly canTransfer = computed(() => this.auth.hasPermission('inventory.transfer'));
  protected readonly canPurchase = computed(() => this.auth.hasPermission('purchases.manage'));
  protected readonly branch = computed(() => this.branches().find((b) => b.id === this.branchId()) ?? null);

  protected readonly shown = computed(() => {
    const q = this.search().trim().toLowerCase();
    const f = this.stateFilter();
    return (this.stock() ?? []).filter(
      (r) =>
        (f === 'all' || r.state === f || (f === 'low' && r.state === 'out')) &&
        (!q ||
          r.name.toLowerCase().includes(q) ||
          (r.sku ?? '').toLowerCase().includes(q) ||
          (r.category_name ?? '').toLowerCase().includes(q)),
    );
  });
  protected readonly totals = computed(() => {
    const rows = this.stock() ?? [];
    return {
      value: rows.reduce((s, r) => s + +r.value, 0),
      low: rows.filter((r) => r.state === 'low').length,
      out: rows.filter((r) => r.state === 'out').length,
    };
  });
  protected readonly alertCount = computed(() => {
    const a = this.alerts();
    return a ? a.low.length + a.out.length + a.expiring.length : 0;
  });

  /** Low/out rows grouped by preferred supplier, so one click drafts one purchase order per supplier. */
  protected readonly bySupplier = computed(() => {
    const a = this.alerts();
    if (!a) return [];
    const groups = new Map<string, { name: string; rows: AlertRow[] }>();
    for (const r of [...a.out, ...a.low]) {
      const key = r.supplier_id ?? '';
      if (!groups.has(key)) groups.set(key, { name: r.supplier_name ?? 'No preferred supplier', rows: [] });
      groups.get(key)!.rows.push(r);
    }
    return [...groups.values()];
  });

  ngOnInit(): void {
    forkJoin({ me: this.tenancy.restaurantMe(), items: this.api.items(), cats: this.api.categories() }).subscribe({
      next: ({ me, items, cats }) => {
        this.items.set(items);
        this.categories.set(cats);
        const active = me.branches.filter((b) => b.is_active);
        this.branches.set(active);
        const first = active.find((b) => b.is_primary) ?? active[0];
        if (first) this.selectBranch(first.id);
        else this.stock.set([]);
      },
      error: (e: ApiError) => this.error.set(e),
    });
    if (this.auth.hasPermission('suppliers.manage') || this.canPurchase() || this.canAdjust()) {
      this.api.suppliers().subscribe({ next: (s) => this.suppliers.set(s), error: () => undefined });
    }
    const off = this.realtime.on<{ branch_id: string }>('inventory.changed', (e) => {
      if (e.branch_id === this.branchId()) this.reload();
    });
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
    this.stock.set(null);
    this.report.set(null);
    this.reload();
    void this.realtime.subscribeBranch(id);
  }

  protected reload(): void {
    const id = this.branchId();
    if (!id) return;
    this.api.stock(id).subscribe({ next: (s) => this.stock.set(s), error: (e: ApiError) => this.error.set(e) });
    this.api.alerts(id).subscribe({ next: (a) => this.alerts.set(a), error: () => undefined });
    this.api.transfers(id).subscribe({ next: (t) => this.transfers.set(t), error: () => undefined });
  }

  protected price(v: string | number): string {
    return formatPrice(v);
  }

  // ---------- stock ----------

  protected move(row: StockRow, type?: ManualType): void {
    const branchId = this.branchId();
    if (!branchId) return;
    const data: MovementDialogData = { branchId, row, type };
    this.dialog
      .open(MovementDialogComponent, { data, width: '560px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((m) => {
        if (!m) return;
        this.snack.open(`${row.name}: now ${qty(m.balance_after)} ${row.unit}.`, undefined, { duration: 2500 });
        this.reload();
      });
  }

  protected history(row: StockRow): void {
    this.dialog.open(HistoryDialogComponent, { data: { branchId: this.branchId(), row }, width: '820px', maxWidth: '96vw' });
  }

  // ---------- items ----------

  protected editItem(item: InventoryItem | null): void {
    const data: ItemDialogData = { item, categories: this.categories(), suppliers: this.suppliers().filter((s) => s.is_active) };
    this.dialog
      .open(ItemDialogComponent, { data, width: '680px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((saved?: InventoryItem) => {
        if (!saved) return;
        this.api.items().subscribe((i) => this.items.set(i));
        this.api.categories().subscribe((c) => this.categories.set(c));
        this.reload();
        const tip = item ? '' : ' Add its opening stock from the Stock tab.';
        this.snack.open(`${saved.name} saved.${tip}`, undefined, { duration: 3500 });
      });
  }

  protected itemOf(id: string): InventoryItem | null {
    return this.items().find((i) => i.id === id) ?? null;
  }

  // ---------- transfers ----------

  protected newTransfer(): void {
    const from = this.branch();
    if (!from) return;
    const data: TransferDialogData = { from, branches: this.branches(), stock: this.stock() ?? [] };
    this.dialog
      .open(TransferDialogComponent, { data, width: '640px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((t?: Transfer) => {
        if (!t) return;
        this.snack.open(`${t.number} sent to ${t.to_branch_name}. It arrives when they press Receive.`, undefined, {
          duration: 4000,
        });
        this.reload();
      });
  }

  protected finishTransfer(t: Transfer, action: 'receive' | 'cancel'): void {
    this.api.finishTransfer(t.id, action).subscribe({
      next: () => this.reload(),
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 }),
    });
  }

  // ---------- alerts → purchase order ----------

  protected orderFor(rows: AlertRow[]): void {
    const branchId = this.branchId();
    if (!branchId || !rows.length) return;
    const data: PurchaseDialogData = {
      purchase: null,
      branches: this.branches(),
      suppliers: this.suppliers().filter((s) => s.is_active),
      items: this.items(),
      prefill: {
        branch_id: branchId,
        supplier_id: rows[0].supplier_id,
        lines: rows.map((r) => ({
          item_id: r.item_id,
          quantity: +r.suggested_quantity > 0 ? r.suggested_quantity : r.reorder_level || '1',
        })),
      },
    };
    this.dialog
      .open(PurchaseDialogComponent, { data, width: '820px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((p) => p && this.snack.open(`${p.number} created — find it under Purchases.`, undefined, { duration: 3500 }));
  }

  // ---------- reports ----------

  protected runReport(): void {
    const id = this.branchId();
    if (!id) return;
    this.api.report(this.reportKind, id, this.reportFrom || undefined, this.reportTo || undefined).subscribe({
      next: (r) => this.report.set(r),
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 }),
    });
  }

  protected isDated(kind: ReportKind): boolean {
    return REPORTS.find((r) => r.kind === kind)?.dated ?? false;
  }

  protected exportCsv(): void {
    const r = this.report();
    if (!r) return;
    const day = new Date().toISOString().slice(0, 10);
    const name = `${r.kind}-${this.branch()?.name ?? 'branch'}-${day}.csv`.replace(/\s+/g, '-').toLowerCase();
    downloadCsv(name, toCsv(r.columns, r.rows));
  }

  protected totalsList(r: Report): [string, string][] {
    return Object.entries(r.totals);
  }
}
