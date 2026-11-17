import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';

import { ApiError } from '../../../core/http/api-error';
import { InventoryService, Purchase } from '../../../core/inventory/inventory.service';
import { formatPrice } from '../../../core/storefront/storefront.models';

/** Record a payment to the supplier (PRD §8.3). */
@Component({
  selector: 'wl-payment-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: '../inventory/inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>Pay for {{ p.number }}</h2>
    <mat-dialog-content>
      <form class="form" id="pay-form" (ngSubmit)="save()">
        <p class="hint">Total {{ price(p.grand_total) }} · paid {{ price(p.amount_paid) }} · <b>due {{ price(due) }}</b></p>
        <div class="grid2">
          <label class="field"><span>Amount (₹)</span>
            <input name="amt" type="number" min="0.01" step="0.01" [max]="due" [(ngModel)]="amount" data-testid="pay-amount" /></label>
          <label class="field"><span>Method</span>
            <select name="m" [(ngModel)]="method">
              <option value="upi">UPI</option><option value="bank">Bank transfer</option><option value="cash">Cash</option>
              <option value="card">Card</option><option value="cheque">Cheque</option>
            </select></label>
          <label class="field"><span>Paid on</span><input name="d" type="date" [(ngModel)]="paidOn" /></label>
          <label class="field"><span>Reference</span><input name="ref" [(ngModel)]="reference" maxlength="60" placeholder="UTR / cheque no." /></label>
        </div>
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="pay-form" [disabled]="busy() || !(+amount > 0)" data-testid="pay-save">Record payment</button>
    </mat-dialog-actions>
  `,
})
export class PaymentDialogComponent {
  protected readonly p = inject<Purchase>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<PaymentDialogComponent, Purchase>);
  private readonly api = inject(InventoryService);
  protected readonly due = Math.round((+this.p.grand_total - +this.p.amount_paid) * 100) / 100;
  protected amount: number | string = this.due;
  protected method = 'upi';
  protected paidOn: string | null = null;
  protected reference = '';
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected price(v: string | number): string {
    return formatPrice(v);
  }

  protected save(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.pay(this.p.id, { amount: String(this.amount), method: this.method, reference: this.reference, paid_on: this.paidOn || null }).subscribe({
      next: (r) => this.ref.close(r),
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}
