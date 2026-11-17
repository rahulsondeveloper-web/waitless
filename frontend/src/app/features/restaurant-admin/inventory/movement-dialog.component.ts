import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';

import { ApiError } from '../../../core/http/api-error';
import { InventoryService, ManualType, Movement, StockRow, qty } from '../../../core/inventory/inventory.service';

export interface MovementDialogData {
  branchId: string;
  row: StockRow;
  type?: ManualType;
}

const TYPES: { type: ManualType; label: string; hint: string }[] = [
  { type: 'opening', label: 'Opening stock', hint: 'The quantity you start with at this branch.' },
  { type: 'addition', label: 'Add stock', hint: 'Stock that came in without a purchase order.' },
  { type: 'wastage', label: 'Wastage', hint: 'Spoiled, expired or thrown away.' },
  { type: 'damage', label: 'Damaged', hint: 'Broken or damaged stock.' },
  { type: 'return', label: 'Return to supplier', hint: 'Stock sent back to the supplier.' },
  { type: 'adjustment', label: 'Count correction', hint: 'Enter what you counted; the difference is recorded.' },
];

/** Record a stock change. Every change keeps a reason and who made it (PRD §8.2). */
@Component({
  selector: 'wl-movement-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>{{ row.name }} · {{ qty(row.on_hand) }} {{ row.unit }} in stock</h2>
    <mat-dialog-content>
      <form class="form" id="move-form" (ngSubmit)="save()">
        <label class="field"><span>What happened?</span>
          <select name="type" [ngModel]="type()" (ngModelChange)="type.set($event)" data-testid="move-type">
            @for (t of types; track t.type) { <option [value]="t.type">{{ t.label }}</option> }
          </select></label>
        <p class="hint">{{ hint() }}</p>
        <div class="grid2">
          <label class="field"><span>{{ type() === 'adjustment' ? 'Counted quantity' : 'Quantity' }} ({{ row.unit }})</span>
            <input name="qty" type="number" min="0" step="0.001" [(ngModel)]="quantity" required data-testid="move-qty" /></label>
          @if (inbound()) {
            <label class="field"><span>Cost (₹ per {{ row.unit }})</span>
              <input name="cost" type="number" min="0" step="0.01" [(ngModel)]="unitCost" /></label>
            @if (row.tracks_expiry) {
              <label class="field"><span>Expiry date</span>
                <input name="exp" type="date" [(ngModel)]="expiry" /></label>
            }
          }
        </div>
        @if (type() === 'adjustment' && quantity !== null && quantity !== '') {
          <p class="hint">Change: <b>{{ diff() > 0 ? '+' : '' }}{{ qty(diff()) }} {{ row.unit }}</b></p>
        }
        <label class="field"><span>Reason{{ type() === 'opening' ? ' (optional)' : '' }}</span>
          <input name="reason" [(ngModel)]="reason" maxlength="200" placeholder="e.g. Milk curdled in the fridge"
                 data-testid="move-reason" /></label>
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="move-form" [disabled]="busy() || !valid()" data-testid="save-move">Save</button>
    </mat-dialog-actions>
  `,
})
export class MovementDialogComponent {
  private readonly data = inject<MovementDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<MovementDialogComponent, Movement>);
  private readonly api = inject(InventoryService);

  protected readonly qty = qty;
  protected readonly types = TYPES;
  protected readonly row = this.data.row;
  protected readonly type = signal<ManualType>(this.data.type ?? (+this.data.row.on_hand === 0 ? 'opening' : 'wastage'));
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected quantity: string | number | null = null;
  protected reason = '';
  protected unitCost: string | number | null = this.data.row.avg_cost !== '0.00' ? this.data.row.avg_cost : null;
  protected expiry: string | null = null;

  protected readonly hint = computed(() => TYPES.find((t) => t.type === this.type())!.hint);
  protected readonly inbound = computed(() => this.type() === 'opening' || this.type() === 'addition');

  protected diff(): number {
    return +(this.quantity ?? 0) - +this.row.on_hand;
  }

  protected valid(): boolean {
    const q = this.quantity === null || this.quantity === '' ? NaN : +this.quantity;
    if (!Number.isFinite(q) || q < 0 || (this.type() !== 'adjustment' && q === 0)) return false;
    return this.type() === 'opening' || !!this.reason.trim();
  }

  protected save(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api
      .move({
        branch_id: this.data.branchId,
        item_id: this.row.item_id,
        type: this.type(),
        quantity: String(this.quantity),
        reason: this.reason,
        unit_cost: this.inbound() && this.unitCost !== null && this.unitCost !== '' ? String(this.unitCost) : null,
        expiry_date: this.inbound() && this.expiry ? this.expiry : null,
      })
      .subscribe({
        next: (m) => this.ref.close(m),
        error: (e: ApiError) => {
          this.busy.set(false);
          this.error.set(e.message);
        },
      });
  }
}
