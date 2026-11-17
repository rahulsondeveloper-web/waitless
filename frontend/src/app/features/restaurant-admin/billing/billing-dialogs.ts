import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';

import { AuthService } from '../../../core/auth/auth.service';
import { Bill, BillPayment, BillingService, METHOD_LABEL, PayMethod, equalShares } from '../../../core/billing/billing.service';
import { ApiError } from '../../../core/http/api-error';
import { newIdempotencyKey } from '../../../core/ordering/ordering.service';
import { formatPrice } from '../../../core/storefront/storefront.models';

const price = (v: string | number) => formatPrice(v);

/** Take a payment: cash with change, UPI, card or another method; "split equally" fills each share. */
@Component({
  selector: 'wl-take-payment-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: '../inventory/inventory-forms.scss',
  styles: `
    .methods { display: flex; flex-wrap: wrap; gap: 0.4rem; }
    .methods button[aria-pressed='true'] { background: var(--wl-primary); color: #fff; }
    .due { font-size: 1.6rem; font-weight: 700; font-variant-numeric: tabular-nums; margin: 0; }
    .change { font-size: 1.1rem; font-weight: 600; color: #2e7d4f; margin: 0; }
    .shares { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: end; }
  `,
  template: `
    <h2 mat-dialog-title>Take payment · {{ bill.label }}{{ bill.table_labels.length ? ' · Table ' + bill.table_labels.join(', ') : '' }}</h2>
    <mat-dialog-content>
      <form class="form" id="pay-form" (ngSubmit)="save()">
        <p class="hint">Due</p>
        <p class="due" data-testid="pay-due">{{ price(bill.due) }}</p>
        <div class="methods" role="group" aria-label="Payment method">
          @for (m of methods; track m) {
            <button mat-stroked-button type="button" [attr.aria-pressed]="method() === m" (click)="method.set(m)" [attr.data-testid]="'method-' + m">
              {{ m === 'other' ? bill.other_method_label : label[m] }}</button>
          }
        </div>
        <div class="shares">
          <label class="field"><span>Split equally between</span>
            <input type="number" min="1" max="50" name="people" [(ngModel)]="people" style="width: 6rem" /></label>
          <button mat-button type="button" (click)="useShare()" [disabled]="people < 2">Use one share{{ people > 1 ? ' (' + price(share()) + ')' : '' }}</button>
        </div>
        <div class="grid2">
          <label class="field"><span>Amount</span>
            <input type="number" min="0.01" step="0.01" [max]="bill.due" name="amount" [(ngModel)]="amount" data-testid="pay-amount" /></label>
          @if (method() === 'cash') {
            <label class="field"><span>Cash handed over</span>
              <input type="number" min="0" step="1" name="tendered" [(ngModel)]="tendered" data-testid="pay-tendered" /></label>
          } @else {
            <label class="field"><span>{{ method() === 'other' ? 'Name / reference' : method() === 'card' ? 'Card / slip no.' : 'UPI ref (optional)' }}</span>
              <input name="ref" [(ngModel)]="reference" maxlength="80" /></label>
          }
        </div>
        @if (method() === 'cash' && change() > 0) { <p class="change" data-testid="pay-change">Give back {{ price(change()) }}</p> }
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="pay-form" [disabled]="busy() || !valid()" data-testid="pay-confirm">
        Record {{ price(+amount || 0) }}</button>
    </mat-dialog-actions>
  `,
})
export class TakePaymentDialogComponent {
  protected readonly bill = inject<Bill>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<TakePaymentDialogComponent, Bill>);
  private readonly api = inject(BillingService);
  protected readonly price = price;
  protected readonly label = METHOD_LABEL;
  protected readonly methods = this.bill.methods.filter((m) => m !== 'gateway');
  protected readonly method = signal<PayMethod>(this.methods[0] ?? 'cash');
  protected amount: string | number = this.bill.due;
  protected tendered: string | number | null = null;
  protected reference = '';
  protected people = 1;
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  private readonly key = newIdempotencyKey(); // a retried click never charges twice

  protected share(): string {
    return equalShares(this.bill.due, this.people)[0];
  }

  protected useShare(): void {
    this.amount = this.share();
  }

  protected change(): number {
    const t = this.tendered === null || this.tendered === '' ? 0 : +this.tendered;
    return t > +this.amount ? Math.round((t - +this.amount) * 100) / 100 : 0;
  }

  protected valid(): boolean {
    const a = +this.amount;
    if (!(a > 0) || a > +this.bill.due + 1e-9) return false;
    return !(this.method() === 'cash' && this.tendered !== null && this.tendered !== '' && +this.tendered < a);
  }

  protected save(): void {
    this.busy.set(true);
    this.error.set(null);
    const cash = this.method() === 'cash';
    this.api
      .pay(
        this.bill.id,
        {
          method: this.method(),
          amount: (+this.amount).toFixed(2),
          tendered: cash && this.tendered !== null && this.tendered !== '' ? (+this.tendered).toFixed(2) : null,
          reference: cash ? '' : this.reference,
        },
        this.key,
      )
      .subscribe({
        next: (b) => this.ref.close(b),
        error: (e: ApiError) => {
          this.busy.set(false);
          this.error.set(e.message);
        },
      });
  }
}

/** Manual discount (% or amount) with a reason; managers stay within the owner's limit. */
@Component({
  selector: 'wl-discount-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: '../inventory/inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>Discount on {{ bill.label }}</h2>
    <mat-dialog-content>
      <form class="form" id="disc-form" (ngSubmit)="save()">
        <p class="hint">Taken off the food ({{ price(base) }} after the serving-time discount), before tax.
          @if (!isOwner()) { Your limit is set by the owner. }</p>
        <div class="grid2">
          <label class="field"><span>Type</span>
            <select name="kind" [(ngModel)]="kind"><option value="pct">Percentage</option><option value="amount">Amount (₹)</option></select></label>
          <label class="field"><span>{{ kind === 'pct' ? 'Discount %' : 'Discount ₹' }}</span>
            <input type="number" min="0" step="0.01" name="v" [(ngModel)]="value" data-testid="disc-value" /></label>
        </div>
        <label class="field"><span>Reason</span>
          <input name="reason" [(ngModel)]="reason" maxlength="200" placeholder="e.g. Regular guest, complaint" data-testid="disc-reason" /></label>
        @if (+value > 0) { <p class="hint">Discount ≈ <b>{{ price(preview()) }}</b></p> }
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (+bill.manual_discount > 0) { <button mat-button type="button" (click)="remove()">Remove discount</button> }
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="disc-form" [disabled]="busy() || !(+value > 0) || !reason.trim()" data-testid="disc-save">Apply</button>
    </mat-dialog-actions>
  `,
})
export class DiscountDialogComponent {
  protected readonly bill = inject<Bill>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<DiscountDialogComponent, Bill>);
  private readonly api = inject(BillingService);
  private readonly auth = inject(AuthService);
  protected readonly price = price;
  protected readonly base = Math.round((+this.bill.subtotal - +this.bill.sla_discount) * 100) / 100;
  protected kind: 'pct' | 'amount' = this.bill.manual_discount_pct ? 'pct' : +this.bill.manual_discount > 0 ? 'amount' : 'pct';
  protected value: string | number = this.bill.manual_discount_pct ?? (+this.bill.manual_discount > 0 ? this.bill.manual_discount : '');
  protected reason = this.bill.manual_discount_reason ?? '';
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly isOwner = computed(() => this.auth.activeTenant()?.role_key === 'owner');

  protected preview(): number {
    return this.kind === 'pct' ? Math.round(this.base * +this.value) / 100 : Math.min(+this.value, this.base);
  }

  protected save(): void {
    this.send(this.kind === 'pct' ? { pct: String(this.value), reason: this.reason } : { amount: String(this.value), reason: this.reason });
  }

  protected remove(): void {
    this.send({ pct: null, amount: null, reason: '' });
  }

  private send(body: { pct?: string | null; amount?: string | null; reason: string }): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.discount(this.bill.id, body).subscribe({
      next: (b) => this.ref.close(b),
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}

/** Refund part or all of a payment; a credit note is issued against the invoice. */
@Component({
  selector: 'wl-refund-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: '../inventory/inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>Refund {{ label[p.method] }} payment</h2>
    <mat-dialog-content>
      <form class="form" id="ref-form" (ngSubmit)="save()">
        <p class="hint">Paid {{ price(p.amount) }}@if (+p.refunded_amount > 0) { · already refunded {{ price(p.refunded_amount) }} }.
          @if (p.method === 'gateway') { The money goes back to the guest's card/UPI. } @else { Give the money back the same way ({{ label[p.method] }}). }</p>
        <label class="field"><span>Amount</span>
          <input type="number" min="0.01" step="0.01" [max]="left" name="amt" [(ngModel)]="amount" data-testid="refund-amount" /></label>
        <label class="field"><span>Reason</span>
          <input name="reason" [(ngModel)]="reason" maxlength="200" data-testid="refund-reason" /></label>
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button color="warn" type="submit" form="ref-form" [disabled]="busy() || !(+amount > 0) || +amount > left || !reason.trim()"
              data-testid="refund-save">Refund</button>
    </mat-dialog-actions>
  `,
})
export class RefundDialogComponent {
  protected readonly p = inject<BillPayment>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<RefundDialogComponent, Bill>);
  private readonly api = inject(BillingService);
  protected readonly price = price;
  protected readonly label = METHOD_LABEL;
  protected readonly left = Math.round((+this.p.amount - +this.p.refunded_amount) * 100) / 100;
  protected amount: string | number = this.left;
  protected reason = '';
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  private readonly key = newIdempotencyKey();

  protected save(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.refund(this.p.id, (+this.amount).toFixed(2), this.reason, this.key).subscribe({
      next: (b) => this.ref.close(b),
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}
