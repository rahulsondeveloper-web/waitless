import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { forkJoin } from 'rxjs';

import { ApiError } from '../../../core/http/api-error';
import { InventoryItem, InventoryService, Purchase, Supplier, qty } from '../../../core/inventory/inventory.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ConfirmData, ConfirmDialogComponent } from '../../../shared/ui/confirm-dialog/confirm-dialog.component';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { PaymentDialogComponent } from './payment-dialog.component';
import { PurchaseDialogComponent, PurchaseDialogData } from './purchase-dialog.component';
import { ReceiveDialogComponent } from './receive-dialog.component';

const STATUS_LABEL: Record<Purchase['status'], string> = {
  draft: 'Draft',
  ordered: 'Ordered',
  received: 'Received',
  cancelled: 'Cancelled',
};
const BADGE: Record<Purchase['status'], string> = { draft: 'waiting', ordered: 'notified', received: 'seated', cancelled: 'cancelled' };

/** Purchase orders (PRD §8.4): draft → ordered → received (stock in) · supplier payments. */
@Component({
  selector: 'wl-purchases-page',
  imports: [DatePipe, MatButtonModule, MatIconModule, MatMenuModule, LoadingStateComponent, ErrorStateComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './purchases.page.html',
  styleUrls: ['../admin-bookings.scss', '../inventory/inventory-forms.scss', './purchases.page.scss'],
})
export class PurchasesPage implements OnInit {
  private readonly api = inject(InventoryService);
  private readonly tenancy = inject(TenancyService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);

  protected readonly statusLabel = STATUS_LABEL;
  protected readonly badge = BADGE;
  protected readonly qty = qty;
  protected readonly purchases = signal<Purchase[] | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly filter = signal<'open' | 'all' | 'unpaid'>('open');
  protected readonly open = signal<string | null>(null);
  protected readonly busy = signal<string | null>(null);
  private branches: Branch[] = [];
  private suppliers: Supplier[] = [];
  private items: InventoryItem[] = [];

  protected readonly shown = computed(() => {
    const list = this.purchases() ?? [];
    const f = this.filter();
    if (f === 'open') return list.filter((p) => p.status === 'draft' || p.status === 'ordered');
    if (f === 'unpaid') return list.filter((p) => p.status === 'received' && p.payment_status !== 'paid');
    return list;
  });
  protected readonly due = computed(() =>
    (this.purchases() ?? [])
      .filter((p) => p.status === 'received')
      .reduce((s, p) => s + +p.grand_total - +p.amount_paid, 0),
  );

  ngOnInit(): void {
    forkJoin({ me: this.tenancy.restaurantMe(), suppliers: this.api.suppliers(), items: this.api.items() }).subscribe({
      next: ({ me, suppliers, items }) => {
        this.branches = me.branches.filter((b) => b.is_active);
        this.suppliers = suppliers;
        this.items = items;
        this.reload();
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }

  protected reload(): void {
    this.api.purchases().subscribe({ next: (p) => this.purchases.set(p), error: (e: ApiError) => this.error.set(e) });
  }

  protected price(v: string | number): string {
    return formatPrice(v);
  }

  protected edit(p: Purchase | null): void {
    const data: PurchaseDialogData = { purchase: p, branches: this.branches, suppliers: this.suppliers.filter((s) => s.is_active), items: this.items };
    this.dialog
      .open(PurchaseDialogComponent, { data, width: '820px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((saved?: Purchase) => {
        if (!saved) return;
        this.snack.open(`${saved.number} saved.`, undefined, { duration: 2500 });
        this.reload();
      });
  }

  protected receive(p: Purchase): void {
    this.dialog
      .open(ReceiveDialogComponent, { data: { purchase: p, items: this.items }, width: '720px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((r?: Purchase) => {
        if (!r) return;
        this.snack.open(`${r.number} received — stock updated.`, undefined, { duration: 3000 });
        this.reload();
      });
  }

  protected pay(p: Purchase): void {
    this.dialog
      .open(PaymentDialogComponent, { data: p, width: '520px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((r?: Purchase) => {
        if (r) this.reload();
      });
  }

  protected action(p: Purchase, a: 'order' | 'cancel'): void {
    const go = () => {
      this.busy.set(p.id);
      this.api.purchaseAction(p.id, a).subscribe({
        next: () => {
          this.busy.set(null);
          this.reload();
        },
        error: (e: ApiError) => {
          this.busy.set(null);
          this.snack.open(e.message, 'OK', { duration: 5000 });
        },
      });
    };
    if (a === 'order') return go();
    const data: ConfirmData = { title: `Cancel ${p.number}?`, message: 'Nothing was added to stock.', confirm: 'Cancel purchase', danger: true };
    this.dialog.open(ConfirmDialogComponent, { data }).afterClosed().subscribe((ok) => ok && go());
  }
}
