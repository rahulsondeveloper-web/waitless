import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';

import { ApiError } from '../../../core/http/api-error';
import {
  InventoryCategory,
  InventoryItem,
  InventoryItemInput,
  InventoryService,
  Supplier,
  UNITS,
  UNIT_LABEL,
} from '../../../core/inventory/inventory.service';

export interface ItemDialogData {
  item: InventoryItem | null;
  categories: InventoryCategory[];
  suppliers: Supplier[];
}

/** Create or edit a raw material (PRD §8.1). */
@Component({
  selector: 'wl-inventory-item-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>{{ data.item ? 'Edit ' + data.item.name : 'New inventory item' }}</h2>
    <mat-dialog-content>
      <form class="form" id="item-form" (ngSubmit)="save()">
        <div class="grid2">
          <label class="field"><span>Name</span>
            <input name="name" [(ngModel)]="f.name" required maxlength="120" data-testid="item-name" /></label>
          <label class="field"><span>SKU / code (optional)</span>
            <input name="sku" [(ngModel)]="f.sku" maxlength="40" /></label>
          <label class="field"><span>Unit</span>
            <select name="unit" [(ngModel)]="f.unit" data-testid="item-unit">
              @for (u of units; track u) { <option [value]="u">{{ unitLabel[u] }}</option> }
            </select></label>
          <div class="inline">
            <label class="field"><span>Category</span>
              <select name="cat" [(ngModel)]="f.category_id">
                <option [ngValue]="null">—</option>
                @for (c of categories(); track c.id) { <option [ngValue]="c.id">{{ c.name }}</option> }
              </select></label>
            <button mat-button type="button" (click)="newCategory()">New</button>
          </div>
          <label class="field"><span>Preferred supplier</span>
            <select name="sup" [(ngModel)]="f.supplier_id">
              <option [ngValue]="null">—</option>
              @for (s of data.suppliers; track s.id) { <option [ngValue]="s.id">{{ s.name }}</option> }
            </select></label>
          <label class="field"><span>Purchase price (₹ per {{ f.unit }})</span>
            <input name="price" type="number" min="0" step="0.01" [(ngModel)]="f.purchase_price" data-testid="item-price" /></label>
          <label class="field"><span>Reorder level ({{ f.unit }})</span>
            <input name="reorder" type="number" min="0" step="0.001" [(ngModel)]="f.reorder_level" data-testid="item-reorder" /></label>
          <label class="field"><span>Minimum stock ({{ f.unit }})</span>
            <input name="min" type="number" min="0" step="0.001" [(ngModel)]="f.min_stock" /></label>
          <label class="field"><span>Storage location</span>
            <input name="loc" [(ngModel)]="f.storage_location" maxlength="80" placeholder="e.g. Cold room" /></label>
        </div>
        <label class="check"><input type="checkbox" name="exp" [(ngModel)]="f.tracks_expiry" /> Track expiry dates (perishable)</label>
        <label class="check"><input type="checkbox" name="act" [(ngModel)]="f.is_active" /> Active</label>
        <p class="hint">You get an alert when stock falls to the reorder level. The unit cannot change once stock is recorded.</p>
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="item-form" [disabled]="busy() || !f.name.trim()" data-testid="save-item">Save</button>
    </mat-dialog-actions>
  `,
})
export class ItemDialogComponent {
  protected readonly data = inject<ItemDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<ItemDialogComponent, InventoryItem>);
  private readonly api = inject(InventoryService);

  protected readonly units = UNITS;
  protected readonly unitLabel = UNIT_LABEL;
  protected readonly categories = signal(this.data.categories);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected f: InventoryItemInput = this.data.item
    ? { ...this.data.item }
    : {
        name: '',
        sku: null,
        category_id: null,
        supplier_id: null,
        unit: 'kg',
        min_stock: '0',
        reorder_level: '0',
        purchase_price: '0',
        tracks_expiry: false,
        storage_location: '',
        is_active: true,
      };

  protected newCategory(): void {
    const name = prompt('Category name (e.g. Dairy, Vegetables, Dry store)')?.trim();
    if (!name) return;
    this.api.createCategory(name).subscribe({
      next: (c) => {
        this.categories.update((list) => [...list, c]);
        this.f.category_id = c.id;
      },
      error: (e: ApiError) => this.error.set(e.message),
    });
  }

  protected save(): void {
    this.busy.set(true);
    this.error.set(null);
    const body: InventoryItemInput = {
      ...this.f,
      sku: this.f.sku?.trim() || null,
      min_stock: String(this.f.min_stock || 0),
      reorder_level: String(this.f.reorder_level || 0),
      purchase_price: String(this.f.purchase_price || 0),
    };
    this.api.saveItem(body, this.data.item?.id).subscribe({
      next: (item) => this.ref.close(item),
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}
