import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { forkJoin, of, switchMap } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import {
  ActiveTable,
  Bill,
  BillPayment,
  BillingService,
  BillingSettings,
  METHOD_LABEL,
  PayMethod,
  SessionBills,
  openBlob,
} from '../../../core/billing/billing.service';
import { ApiError } from '../../../core/http/api-error';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { DiscountDialogComponent, RefundDialogComponent, TakePaymentDialogComponent } from './billing-dialogs';

const ALL_METHODS: PayMethod[] = ['cash', 'upi', 'card', 'gateway', 'other'];

/** Billing & POS (PRD §9): active tables, bills with every discount and tax, split/merge, payments, invoices. */
@Component({
  selector: 'wl-billing-page',
  imports: [
    DatePipe,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatSlideToggleModule,
    MatTabsModule,
    LoadingStateComponent,
    ErrorStateComponent,
    EmptyStateComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './billing.page.html',
  styleUrls: ['../admin-bookings.scss', '../inventory/inventory-forms.scss', './billing.page.scss'],
})
export class BillingPage implements OnInit {
  private readonly api = inject(BillingService);
  private readonly tenancy = inject(TenancyService);
  private readonly realtime = inject(RealtimeService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly methodLabel = METHOD_LABEL;
  protected readonly allMethods = ALL_METHODS;
  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly tables = signal<ActiveTable[] | null>(null);
  protected readonly selected = signal<string | null>(null);
  protected readonly current = signal<SessionBills | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busy = signal<string | null>(null);
  protected readonly picked = signal<Record<string, boolean>>({});
  protected readonly settings = signal<BillingSettings | null>(null);
  protected readonly live = signal(false);

  protected readonly canCollect = computed(() => this.auth.hasPermission('payments.collect'));
  protected readonly canDiscount = computed(() => this.auth.hasPermission('billing.discount.apply'));
  protected readonly canRefund = computed(() => this.auth.hasPermission('payments.refund'));
  protected readonly canSettings = computed(() => this.auth.hasPermission('settings.manage'));
  protected readonly canClose = computed(() => this.auth.hasPermission('tables.operate'));
  protected readonly pickedCount = computed(() => Object.values(this.picked()).filter(Boolean).length);
  protected readonly mergeable = computed(() => (this.tables() ?? []).filter((t) => t.session_id !== this.selected() && !t.paid && t.orders));

  ngOnInit(): void {
    this.tenancy.restaurantMe().subscribe({
      next: (me) => {
        const active = me.branches.filter((b) => b.is_active);
        this.branches.set(active);
        const first = active.find((b) => b.is_primary) ?? active[0];
        if (first) this.selectBranch(first.id);
        else this.tables.set([]);
      },
      error: (e: ApiError) => this.error.set(e),
    });
    this.api.settings().subscribe({ next: (s) => this.settings.set(s), error: () => undefined });
    const refresh = (e: { branch_id: string }) => {
      if (e.branch_id !== this.branchId()) return;
      this.loadTables();
      if (this.selected()) this.open(this.selected()!, false);
    };
    const offs = [
      this.realtime.on<{ branch_id: string }>('bills.changed', refresh),
      this.realtime.on<{ branch_id: string }>('orders.changed', refresh),
      this.realtime.on<{ branch_id: string }>('tables.changed', (e) => e.branch_id === this.branchId() && this.loadTables()),
    ];
    this.destroyRef.onDestroy(() => {
      offs.forEach((off) => off());
      const b = this.branchId();
      if (b) this.realtime.unsubscribeBranch(b);
    });
  }

  protected selectBranch(id: string): void {
    const previous = this.branchId();
    if (previous && previous !== id) this.realtime.unsubscribeBranch(previous);
    this.branchId.set(id);
    this.selected.set(null);
    this.current.set(null);
    this.loadTables();
    void this.realtime.subscribeBranch(id).then((ok) => this.live.set(ok));
  }

  protected loadTables(): void {
    const id = this.branchId();
    if (!id) return;
    this.api.tables(id).subscribe({ next: (t) => this.tables.set(t), error: (e: ApiError) => this.error.set(e) });
  }

  protected open(sessionId: string, reset = true): void {
    this.selected.set(sessionId);
    if (reset) {
      this.current.set(null);
      this.picked.set({});
    }
    this.api.sessionBills(sessionId).subscribe({
      next: (s) => this.current.set(s),
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 }),
    });
  }

  protected price(v: string | number): string {
    return formatPrice(v);
  }

  protected n(v: string): number {
    return +v;
  }

  protected tableName(t: { table_labels: string[]; session_code: string }): string {
    return t.table_labels.length ? `Table ${t.table_labels.join(', ')}` : t.session_code;
  }

  private after(msg?: string): (b: unknown) => void {
    return () => {
      this.busy.set(null);
      if (msg) this.snack.open(msg, undefined, { duration: 2500 });
      if (this.selected()) this.open(this.selected()!, false);
      this.loadTables();
    };
  }

  private fail = (e: ApiError) => {
    this.busy.set(null);
    this.snack.open(e.message, 'OK', { duration: 6000 });
  };

  // ---------- bill actions ----------

  protected pay(b: Bill): void {
    this.dialog
      .open(TakePaymentDialogComponent, { data: b, width: '520px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((r?: Bill) => r && this.after(r.status === 'paid' ? `${r.label} paid — invoice ${r.invoices[0]?.number ?? ''}` : 'Payment recorded.')(r));
  }

  protected discount(b: Bill): void {
    this.dialog
      .open(DiscountDialogComponent, { data: b, width: '480px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((r?: Bill) => r && this.after('Discount updated.')(r));
  }

  protected refund(p: BillPayment): void {
    this.dialog
      .open(RefundDialogComponent, { data: p, width: '480px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((r?: Bill) => r && this.after('Refunded — a credit note was issued.')(r));
  }

  protected toggle(lineId: string, on: boolean): void {
    this.picked.set({ ...this.picked(), [lineId]: on });
  }

  protected split(b: Bill): void {
    const ids = b.lines.filter((l) => this.picked()[l.order_item_id]).map((l) => l.order_item_id);
    if (!ids.length) return;
    this.busy.set(b.id);
    this.api.split(b.id, ids).subscribe({
      next: (s) => {
        this.busy.set(null);
        this.picked.set({});
        this.current.set(s);
        this.snack.open(`${ids.length} line${ids.length > 1 ? 's' : ''} moved to a new bill.`, undefined, { duration: 2500 });
      },
      error: this.fail,
    });
  }

  /** Bring another table's open bill into this one (tables joined together). */
  protected mergeFrom(b: Bill, t: ActiveTable): void {
    this.busy.set(b.id);
    this.api
      .sessionBills(t.session_id)
      .pipe(
        switchMap((s) => {
          const src = s.bills.find((x) => x.status === 'open' && !x.locked && x.lines.length);
          if (!src) throw new ApiError(409, 'NOTHING_TO_MERGE', `${this.tableName(t)} has no open bill to merge.`);
          return this.api.merge(b.id, src.id);
        }),
      )
      .subscribe({ next: this.after(`${this.tableName(t)} merged into this bill.`), error: this.fail });
  }

  protected confirmUpi(p: BillPayment): void {
    this.busy.set(p.id);
    this.api.confirmUpi(p.id).subscribe({ next: this.after(`UPI payment of ${this.price(p.amount)} confirmed.`), error: this.fail });
  }

  protected rejectUpi(p: BillPayment): void {
    if (!confirm(`Mark the UPI payment of ${this.price(p.amount)} as not received? The guest can pay again.`)) return;
    this.busy.set(p.id);
    this.api.rejectUpi(p.id).subscribe({ next: this.after('Marked as not received.'), error: this.fail });
  }

  protected settle(b: Bill): void {
    this.busy.set(b.id);
    this.api.settle(b.id).subscribe({ next: this.after(`${b.label} closed.`), error: this.fail });
  }

  protected voidBill(b: Bill): void {
    const reason = prompt(`Why write off ${b.label} (${this.price(b.grand_total)})?`)?.trim();
    if (!reason) return;
    this.busy.set(b.id);
    this.api.void(b.id, reason).subscribe({ next: this.after(`${b.label} written off.`), error: this.fail });
  }

  protected pdf(invoiceId: string, receipt = false): void {
    this.api.invoicePdf(invoiceId, receipt).subscribe({ next: openBlob, error: this.fail });
  }

  // ---------- the visit ----------

  protected reopen(): void {
    const s = this.current();
    if (!s) return;
    this.api.reopen(s.session_id).subscribe({ next: this.after('Table reopened for more orders.'), error: this.fail });
  }

  protected closeTable(): void {
    const s = this.current();
    if (!s) return;
    this.busy.set('close');
    this.api.close(s.session_id).subscribe({
      next: () => {
        this.busy.set(null);
        this.snack.open(`${this.tableName(s)} closed — table set to cleaning.`, undefined, { duration: 3000 });
        this.selected.set(null);
        this.current.set(null);
        this.loadTables();
      },
      error: this.fail,
    });
  }

  // ---------- settings ----------

  protected toggleMethod(m: PayMethod, on: boolean): void {
    const s = this.settings();
    if (!s) return;
    const set = new Set(s.methods);
    if (on) set.add(m);
    else set.delete(m);
    this.settings.set({ ...s, methods: ALL_METHODS.filter((x) => set.has(x)) });
  }

  protected patchSettings<K extends keyof BillingSettings>(k: K, v: BillingSettings[K]): void {
    const s = this.settings();
    if (s) this.settings.set({ ...s, [k]: v });
  }

  protected saveSettings(): void {
    const s = this.settings();
    if (!s) return;
    this.busy.set('settings');
    const body = { ...s, service_charge_pct: String(s.service_charge_pct || 0), service_charge_tax_pct: String(s.service_charge_tax_pct || 0) };
    forkJoin([this.api.saveSettings(body), of(null)]).subscribe({
      next: ([saved]) => {
        this.busy.set(null);
        this.settings.set(saved);
        this.snack.open('Billing settings saved. Open bills use them from now on.', undefined, { duration: 3000 });
      },
      error: this.fail,
    });
  }
}
