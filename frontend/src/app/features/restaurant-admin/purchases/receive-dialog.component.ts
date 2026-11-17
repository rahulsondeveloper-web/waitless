import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';

import { ApiError } from '../../../core/http/api-error';
import { InventoryItem, InventoryService, Purchase } from '../../../core/inventory/inventory.service';
import { formatPrice } from '../../../core/storefront/storefront.models';

/** Goods arrived: confirm what came (short deliveries allowed) and expiry dates → stock comes in. */
@Component({
  selector: 'wl-receive-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: '../inventory/inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>Receive {{ p.number }}{{ p.supplier_name ? ' from ' + p.supplier_name : '' }}</h2>
    <mat-dialog-content>
      <form class="form" id="rc-form" (ngSubmit)="save()">
        <p class="hint">Enter what actually arrived. The bill is recalculated for short deliveries.</p>
        <div class="lines">
          @for (l of lines; track l.item_id; let i = $index) {
            <div class="line">
              <span><b>{{ l.name }}</b><br /><small class="hint">ordered {{ l.ordered }} {{ l.unit }} at {{ price(l.unit_price) }}</small></span>
              <label class="field"><span>Received ({{ l.unit }})</span>
                <input [name]="'r' + i" type="number" min="0" step="0.001" [(ngModel)]="l.received" data-testid="rc-qty" /></label>
              @if (l.tracks_expiry) {
                <label class="field"><span>Expiry date</span>
                  <input [name]="'e' + i" type="date" [(ngModel)]="l.expiry" required data-testid="rc-expiry" /></label>
              } @else { <span></span> }
              <span></span>
            </div>
          }
        </div>
        <div class="grid2">
          <label class="field"><span>Supplier invoice no.</span><input name="inv" [(ngModel)]="invoice" maxlength="40" /></label>
          <label class="field"><span>Invoice date</span><input name="invd" type="date" [(ngModel)]="invoiceDate" /></label>
        </div>
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="rc-form" [disabled]="busy()" data-testid="rc-save">Add to stock</button>
    </mat-dialog-actions>
  `,
})
export class ReceiveDialogComponent {
  private readonly data = inject<{ purchase: Purchase; items: InventoryItem[] }>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<ReceiveDialogComponent, Purchase>);
  private readonly api = inject(InventoryService);
  protected readonly p = this.data.purchase;
  protected lines = this.p.items.map((l) => ({
    item_id: l.item_id,
    name: l.name,
    unit: l.unit,
    unit_price: l.unit_price,
    ordered: +l.quantity,
    received: +l.quantity as number | string,
    expiry: null as string | null,
    tracks_expiry: !!this.data.items.find((i) => i.id === l.item_id)?.tracks_expiry,
  }));
  protected invoice = this.p.invoice_number;
  protected invoiceDate: string | null = this.p.invoice_date;
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected price(v: string): string {
    return formatPrice(v);
  }

  protected save(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api
      .receive(this.p.id, {
        items: this.lines.map((l) => ({ item_id: l.item_id, received_quantity: String(l.received || 0), expiry_date: l.expiry || null })),
        invoice_number: this.invoice,
        invoice_date: this.invoiceDate || null,
      })
      .subscribe({
        next: (r) => this.ref.close(r),
        error: (e: ApiError) => {
          this.busy.set(false);
          this.error.set(e.message);
        },
      });
  }
}
