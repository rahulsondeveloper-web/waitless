import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';

import { ApiError } from '../../../core/http/api-error';
import { InventoryItem, InventoryService, Purchase, PurchaseInput, Supplier } from '../../../core/inventory/inventory.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { Branch } from '../../../core/tenancy/tenancy.models';

export interface PurchaseDialogData {
  purchase: Purchase | null;
  branches: Branch[];
  suppliers: Supplier[];
  items: InventoryItem[];
  /** From Inventory → Alerts: a draft for the suggested quantities. */
  prefill?: { branch_id: string; supplier_id: string | null; lines: { item_id: string; quantity: string }[] };
}

interface Line {
  item_id: string;
  quantity: string | number;
  unit_price: string | number;
  tax_pct: string | number;
}

/** Create or edit a purchase order (PRD §8.4): supplier, branch, dates, items, price and tax. */
@Component({
  selector: 'wl-purchase-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: '../inventory/inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>{{ data.purchase ? 'Edit ' + data.purchase.number : 'New purchase order' }}</h2>
    <mat-dialog-content>
      <form class="form" id="po-form" (ngSubmit)="save('draft')">
        <div class="grid2">
          <label class="field"><span>Supplier</span>
            <select name="sup" [(ngModel)]="supplierId" data-testid="po-supplier">
              <option [ngValue]="null">—</option>
              @for (s of data.suppliers; track s.id) { <option [ngValue]="s.id">{{ s.name }}</option> }
            </select></label>
          <label class="field"><span>Deliver to branch</span>
            <select name="br" [(ngModel)]="branchId">
              @for (b of data.branches; track b.id) { <option [value]="b.id">{{ b.name }}</option> }
            </select></label>
          <label class="field"><span>Order date</span><input name="od" type="date" [(ngModel)]="orderDate" /></label>
          <label class="field"><span>Expected</span><input name="ed" type="date" [(ngModel)]="expectedDate" /></label>
          <label class="field"><span>Supplier invoice no. (optional)</span>
            <input name="inv" [(ngModel)]="invoiceNumber" maxlength="40" /></label>
        </div>
        <div class="lines">
          @for (l of lines; track $index; let i = $index) {
            <div class="line">
              <label class="field"><span>Item</span>
                <select [name]="'it' + i" [(ngModel)]="l.item_id" (ngModelChange)="pick(l, $event)" data-testid="po-item">
                  <option value="">Choose…</option>
                  @for (it of activeItems; track it.id) { <option [value]="it.id">{{ it.name }} ({{ it.unit }})</option> }
                </select></label>
              <label class="field"><span>Qty {{ unitOf(l.item_id) }}</span>
                <input [name]="'q' + i" type="number" min="0" step="0.001" [(ngModel)]="l.quantity" data-testid="po-qty" /></label>
              <label class="field"><span>Price (₹)</span>
                <input [name]="'p' + i" type="number" min="0" step="0.01" [(ngModel)]="l.unit_price" data-testid="po-price" /></label>
              <label class="field"><span>Tax %</span>
                <input [name]="'t' + i" type="number" min="0" max="40" step="0.5" [(ngModel)]="l.tax_pct" /></label>
              <button mat-icon-button type="button" (click)="lines.splice(i, 1)" [disabled]="lines.length === 1" aria-label="Remove line">
                <mat-icon>delete</mat-icon></button>
            </div>
          }
        </div>
        <button mat-button type="button" (click)="lines.push({ item_id: '', quantity: '', unit_price: '', tax_pct: 0 })">
          <mat-icon>add</mat-icon>Add item</button>
        <div class="total"><span>Before tax {{ price(subtotal()) }}</span><span>Tax {{ price(tax()) }}</span>
          <b data-testid="po-total">Total {{ price(subtotal() + tax()) }}</b></div>
        <label class="field"><span>Notes</span><textarea name="notes" [(ngModel)]="notes" maxlength="2000"></textarea></label>
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-stroked-button type="submit" form="po-form" [disabled]="busy() || !valid()" data-testid="po-save-draft">Save draft</button>
      <button mat-flat-button type="button" (click)="save('ordered')" [disabled]="busy() || !valid()" data-testid="po-save-ordered">
        Save as ordered</button>
    </mat-dialog-actions>
  `,
})
export class PurchaseDialogComponent {
  protected readonly data = inject<PurchaseDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<PurchaseDialogComponent, Purchase>);
  private readonly api = inject(InventoryService);

  protected readonly activeItems = this.data.items.filter((i) => i.is_active);
  protected supplierId: string | null = this.data.purchase?.supplier_id ?? this.data.prefill?.supplier_id ?? null;
  protected branchId = this.data.purchase?.branch_id ?? this.data.prefill?.branch_id ?? this.data.branches[0]?.id ?? '';
  protected orderDate: string | null = this.data.purchase?.order_date ?? null;
  protected expectedDate: string | null = this.data.purchase?.expected_date ?? null;
  protected invoiceNumber = this.data.purchase?.invoice_number ?? '';
  protected notes = this.data.purchase?.notes ?? '';
  protected lines: Line[] = this.data.purchase
    ? this.data.purchase.items.map((l) => ({ item_id: l.item_id, quantity: +l.quantity, unit_price: l.unit_price, tax_pct: l.tax_pct }))
    : this.data.prefill?.lines.map((l) => ({ item_id: l.item_id, quantity: +l.quantity, unit_price: this.priceOf(l.item_id), tax_pct: 0 })) ?? [
        { item_id: '', quantity: '', unit_price: '', tax_pct: 0 },
      ];
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  private priceOf(id: string): string {
    return this.data.items.find((i) => i.id === id)?.purchase_price ?? '0';
  }

  protected pick(l: Line, id: string): void {
    if (id && (l.unit_price === '' || +l.unit_price === 0)) l.unit_price = this.priceOf(id);
  }

  protected unitOf(id: string): string {
    const it = this.data.items.find((x) => x.id === id);
    return it ? `(${it.unit})` : '';
  }

  protected subtotal(): number {
    return this.lines.reduce((s, l) => s + Math.round(+l.quantity * +l.unit_price * 100) / 100, 0);
  }

  protected tax(): number {
    return this.lines.reduce((s, l) => s + Math.round(((Math.round(+l.quantity * +l.unit_price * 100) / 100) * +l.tax_pct) / 100 * 100) / 100, 0);
  }

  protected price(v: number): string {
    return formatPrice(v);
  }

  protected valid(): boolean {
    const ids = this.lines.map((l) => l.item_id);
    return !!this.branchId && new Set(ids).size === ids.length && this.lines.every((l) => l.item_id && +l.quantity > 0 && +l.unit_price >= 0 && l.unit_price !== '');
  }

  protected save(status: 'draft' | 'ordered'): void {
    if (!this.valid()) return;
    this.busy.set(true);
    this.error.set(null);
    const body: PurchaseInput = {
      branch_id: this.branchId,
      supplier_id: this.supplierId,
      order_date: this.orderDate || null,
      expected_date: this.expectedDate || null,
      invoice_number: this.invoiceNumber,
      notes: this.notes,
      status,
      items: this.lines.map((l) => ({
        item_id: l.item_id,
        quantity: String(l.quantity),
        unit_price: String(l.unit_price),
        tax_pct: String(l.tax_pct || 0),
      })),
    };
    this.api.savePurchase(body, this.data.purchase?.id).subscribe({
      next: (p) => this.ref.close(p),
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}
