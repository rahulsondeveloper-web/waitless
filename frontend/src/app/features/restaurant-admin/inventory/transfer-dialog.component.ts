import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';

import { ApiError } from '../../../core/http/api-error';
import { InventoryService, StockRow, Transfer, qty } from '../../../core/inventory/inventory.service';
import { Branch } from '../../../core/tenancy/tenancy.models';

export interface TransferDialogData {
  from: Branch;
  branches: Branch[];
  stock: StockRow[];
}

/** Send stock to another branch. It leaves now and arrives when that branch presses Receive. */
@Component({
  selector: 'wl-transfer-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>Send stock from {{ data.from.name }}</h2>
    <mat-dialog-content>
      <form class="form" id="tr-form" (ngSubmit)="save()">
        <label class="field"><span>To branch</span>
          <select name="to" [(ngModel)]="to" required data-testid="transfer-to">
            @for (b of targets; track b.id) { <option [value]="b.id">{{ b.name }}</option> }
          </select></label>
        <div class="lines">
          @for (l of lines; track $index; let i = $index) {
            <div class="line">
              <label class="field"><span>Item</span>
                <select [name]="'it' + i" [(ngModel)]="l.item_id" data-testid="transfer-item">
                  <option value="">Choose…</option>
                  @for (s of available; track s.item_id) {
                    <option [value]="s.item_id">{{ s.name }} ({{ qty(s.on_hand) }} {{ s.unit }})</option>
                  }
                </select></label>
              <label class="field"><span>Quantity {{ unitOf(l.item_id) }}</span>
                <input [name]="'q' + i" type="number" min="0" step="0.001" [(ngModel)]="l.quantity" data-testid="transfer-qty" /></label>
              <button mat-icon-button type="button" (click)="lines.splice(i, 1)" [disabled]="lines.length === 1" aria-label="Remove line">
                <mat-icon>delete</mat-icon></button>
            </div>
          }
        </div>
        <button mat-button type="button" (click)="lines.push({ item_id: '', quantity: '' })"><mat-icon>add</mat-icon>Add item</button>
        <label class="field"><span>Note (optional)</span><input name="notes" [(ngModel)]="notes" maxlength="300" /></label>
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="tr-form" [disabled]="busy() || !valid()" data-testid="send-transfer">Send</button>
    </mat-dialog-actions>
  `,
})
export class TransferDialogComponent {
  protected readonly data = inject<TransferDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<TransferDialogComponent, Transfer>);
  private readonly api = inject(InventoryService);
  protected readonly qty = qty;
  protected readonly targets = this.data.branches.filter((b) => b.id !== this.data.from.id);
  protected readonly available = this.data.stock.filter((s) => +s.on_hand > 0);
  protected to = this.targets[0]?.id ?? '';
  protected lines: { item_id: string; quantity: string | number }[] = [{ item_id: '', quantity: '' }];
  protected notes = '';
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected unitOf(id: string): string {
    const s = this.data.stock.find((x) => x.item_id === id);
    return s ? `(${s.unit})` : '';
  }

  protected valid(): boolean {
    return !!this.to && this.lines.every((l) => l.item_id && +l.quantity > 0);
  }

  protected save(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api
      .sendTransfer({
        from_branch_id: this.data.from.id,
        to_branch_id: this.to,
        items: this.lines.map((l) => ({ item_id: l.item_id, quantity: String(l.quantity) })),
        notes: this.notes,
      })
      .subscribe({
        next: (t) => this.ref.close(t),
        error: (e: ApiError) => {
          this.busy.set(false);
          this.error.set(e.message);
        },
      });
  }
}
