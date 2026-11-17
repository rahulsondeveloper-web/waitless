import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { InventoryService, Purchase, Supplier, SupplierInput } from '../../../core/inventory/inventory.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/** Add or edit a supplier's contact details (PRD §8.3). */
@Component({
  selector: 'wl-supplier-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: '../inventory/inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>{{ data ? 'Edit ' + data.name : 'New supplier' }}</h2>
    <mat-dialog-content>
      <form class="form" id="sup-form" (ngSubmit)="save()">
        <div class="grid2">
          <label class="field"><span>Name</span><input name="n" [(ngModel)]="f.name" required maxlength="120" data-testid="sup-name" /></label>
          <label class="field"><span>Contact person</span><input name="c" [(ngModel)]="f.contact_name" maxlength="80" /></label>
          <label class="field"><span>Phone</span><input name="p" type="tel" [(ngModel)]="f.phone" maxlength="20" data-testid="sup-phone" /></label>
          <label class="field"><span>Email</span><input name="e" type="email" [(ngModel)]="f.email" maxlength="120" /></label>
          <label class="field"><span>GSTIN</span><input name="g" [(ngModel)]="f.gstin" maxlength="20" /></label>
        </div>
        <label class="field"><span>Address</span><input name="a" [(ngModel)]="f.address" maxlength="300" /></label>
        <label class="field"><span>Notes</span><textarea name="no" [(ngModel)]="f.notes" maxlength="2000"></textarea></label>
        <label class="check"><input type="checkbox" name="act" [(ngModel)]="f.is_active" /> Active</label>
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="sup-form" [disabled]="busy() || !f.name.trim()" data-testid="save-supplier">Save</button>
    </mat-dialog-actions>
  `,
})
export class SupplierDialogComponent {
  protected readonly data = inject<Supplier | null>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<SupplierDialogComponent, Supplier>);
  private readonly api = inject(InventoryService);
  protected f: SupplierInput = this.data
    ? { ...this.data }
    : { name: '', contact_name: '', phone: '', email: '', address: '', gstin: '', notes: '', is_active: true };
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected save(): void {
    this.busy.set(true);
    const { name, contact_name, phone, email, address, gstin, notes, is_active } = this.f;
    this.api.saveSupplier({ name, contact_name, phone, email, address, gstin, notes, is_active }, this.data?.id).subscribe({
      next: (s) => this.ref.close(s),
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}

/** Suppliers (PRD §8.3): contacts, purchase totals, what is still owed, purchase history. */
@Component({
  selector: 'wl-suppliers-page',
  imports: [DatePipe, MatButtonModule, MatIconModule, LoadingStateComponent, ErrorStateComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../admin-bookings.scss', '../inventory/inventory-forms.scss'],
  styles: `
    .sub { margin-top: 0.5rem; }
    a { color: var(--wl-primary); }
  `,
  template: `
    <header class="page-head">
      <div>
        <h1>Suppliers</h1>
        <p class="muted">Who you buy from, how much, and what is still to pay.</p>
      </div>
      @if (canManage()) {
        <div class="head-tools">
          <button mat-flat-button (click)="edit(null)" data-testid="new-supplier"><mat-icon>add</mat-icon>New supplier</button>
        </div>
      }
    </header>
    @if (error(); as e) {
      <wl-error-state [message]="e.message" (retry)="load()" />
    } @else if (!suppliers()) {
      <wl-loading-state />
    } @else if (!suppliers()!.length) {
      <wl-empty-state icon="local_shipping" title="No suppliers yet" message="Add the vendors you buy ingredients from." />
    } @else {
      <ul class="rows">
        @for (s of suppliers(); track s.id) {
          <li class="row" data-testid="supplier-row">
            <span class="row__lead"><mat-icon>local_shipping</mat-icon></span>
            <div class="row__main">
              <div><b>{{ s.name }}</b> @if (!s.is_active) { <span class="badge" data-status="cancelled">Inactive</span> }</div>
              <span class="muted">
                {{ s.contact_name }}@if (s.phone) { · <a [href]="'tel:' + s.phone">{{ s.phone }}</a> }
                @if (s.email) { · <a [href]="'mailto:' + s.email">{{ s.email }}</a> }
                @if (s.gstin) { · GSTIN {{ s.gstin }} }
              </span>
              <span class="muted">{{ s.purchases_count }} purchases · {{ price(s.purchases_total) }}
                @if (+s.outstanding > 0) { · <b>{{ price(s.outstanding) }} to pay</b> }</span>
              @if (history()[s.id]; as list) {
                <table class="table sub">
                  <thead><tr><th>Number</th><th>Date</th><th>Status</th><th class="num">Total</th><th class="num">Paid</th></tr></thead>
                  <tbody>
                    @for (p of list; track p.id) {
                      <tr><td>{{ p.number }}</td><td>{{ p.order_date | date: 'd MMM y' }}</td><td>{{ p.status }}</td>
                        <td class="num">{{ price(p.grand_total) }}</td><td class="num">{{ price(p.amount_paid) }}</td></tr>
                    } @empty { <tr><td colspan="5" class="muted">No purchases yet.</td></tr> }
                  </tbody>
                </table>
              }
            </div>
            <div class="row__actions">
              @if (canPurchase()) {
                <button mat-button (click)="toggleHistory(s)">{{ history()[s.id] ? 'Hide history' : 'History' }}</button>
              }
              @if (canManage()) { <button mat-icon-button (click)="edit(s)" aria-label="Edit supplier"><mat-icon>edit</mat-icon></button> }
            </div>
          </li>
        }
      </ul>
    }
  `,
})
export class SuppliersPage implements OnInit {
  private readonly api = inject(InventoryService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  private readonly auth = inject(AuthService);
  protected readonly suppliers = signal<Supplier[] | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly history = signal<Record<string, Purchase[]>>({});
  protected readonly canManage = computed(() => this.auth.hasPermission('suppliers.manage'));
  protected readonly canPurchase = computed(() => this.auth.hasPermission('purchases.manage'));

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.error.set(null);
    this.api.suppliers().subscribe({ next: (s) => this.suppliers.set(s), error: (e: ApiError) => this.error.set(e) });
  }

  protected price(v: string): string {
    return formatPrice(v);
  }

  protected edit(s: Supplier | null): void {
    this.dialog
      .open(SupplierDialogComponent, { data: s, width: '640px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((saved?: Supplier) => {
        if (!saved) return;
        this.snack.open(`${saved.name} saved.`, undefined, { duration: 2000 });
        this.load();
      });
  }

  protected toggleHistory(s: Supplier): void {
    const h = { ...this.history() };
    if (h[s.id]) {
      delete h[s.id];
      this.history.set(h);
      return;
    }
    this.api.purchases({ supplier_id: s.id }).subscribe((list) => this.history.set({ ...this.history(), [s.id]: list }));
  }
}
