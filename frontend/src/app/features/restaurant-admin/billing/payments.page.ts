import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { forkJoin } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { BillPayment, BillingService, Invoice, METHOD_LABEL, PayMethod, openBlob } from '../../../core/billing/billing.service';
import { ApiError } from '../../../core/http/api-error';
import { downloadCsv, toCsv } from '../../../core/inventory/inventory.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { RefundDialogComponent } from './billing-dialogs';

/** Payment history (PRD §9): the day's payments by method, refunds, invoices and credit notes. */
@Component({
  selector: 'wl-payments-page',
  imports: [DatePipe, MatButtonModule, MatIconModule, LoadingStateComponent, ErrorStateComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../admin-bookings.scss', '../inventory/inventory-forms.scss'],
  styles: `
    .bar { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: end; margin: 1rem 0; }
    .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.6rem; margin-bottom: 1rem; }
    .tile { background: var(--wl-surface); border: 1px solid var(--wl-line); border-radius: 12px; padding: 0.7rem 0.9rem; }
    .tile b { display: block; font-size: 1.25rem; font-variant-numeric: tabular-nums; }
    h2 { font-size: 1.05rem; margin: 1.2rem 0 0.5rem; }
    .scroll { overflow-x: auto; }
  `,
  template: `
    <header class="page-head">
      <div><h1>Payments</h1><p class="muted">Every payment, refund and invoice of the day.</p></div>
      <div class="head-tools">
        @if (branches().length > 1) {
          <label class="field"><span>Branch</span>
            <select [value]="branchId() ?? ''" (change)="branchId.set($any($event.target).value); load()" aria-label="Branch">
              @for (b of branches(); track b.id) { <option [value]="b.id">{{ b.name }}</option> }
            </select></label>
        }
        <label class="field"><span>Day</span>
          <input type="date" [value]="day()" (change)="day.set($any($event.target).value); load()" data-testid="payments-day" /></label>
      </div>
    </header>
    @if (error(); as e) {
      <wl-error-state [message]="e.message" (retry)="load()" />
    } @else if (!payments()) {
      <wl-loading-state />
    } @else {
      <div class="tiles" data-testid="payment-totals">
        <div class="tile"><span class="muted">Collected</span><b>{{ price(totals().net) }}</b></div>
        @for (m of totals().byMethod; track m.method) {
          <div class="tile"><span class="muted">{{ label[m.method] }}</span><b>{{ price(m.amount) }}</b></div>
        }
        @if (totals().refunded > 0) { <div class="tile"><span class="muted">Refunded</span><b>{{ price(totals().refunded) }}</b></div> }
      </div>
      @if (!payments()!.length) {
        <wl-empty-state icon="payments" title="No payments on this day" message="Payments taken on the Billing screen or online appear here." />
      } @else {
        <div class="bar"><button mat-stroked-button (click)="csv()"><mat-icon>download</mat-icon>CSV</button></div>
        <div class="scroll">
          <table class="table" data-testid="payments-table">
            <thead><tr><th>Time</th><th>Table</th><th>Method</th><th>Invoice</th><th>By</th><th class="num">Amount</th><th></th></tr></thead>
            <tbody>
              @for (p of payments(); track p.id) {
                <tr [class.muted]="p.status !== 'captured'">
                  <td>{{ p.created_at | date: 'HH:mm' }}</td>
                  <td>{{ p.table_labels.length ? p.table_labels.join(', ') : '—' }} · {{ p.bill_label }}</td>
                  <td>{{ p.method === 'other' ? p.method_label || 'Other' : label[p.method] }}{{ p.reference ? ' · ' + p.reference : '' }}
                    @if (p.status !== 'captured') { ({{ p.status }}) }</td>
                  <td>{{ p.invoice_number ?? '—' }}</td>
                  <td>{{ p.received_by_name ?? (p.method === 'gateway' ? 'Guest (online)' : '—') }}</td>
                  <td class="num">{{ price(p.amount) }}@if (+p.refunded_amount > 0) { <br /><small class="neg">−{{ price(p.refunded_amount) }}</small> }</td>
                  <td>@if (canRefund() && p.status === 'captured' && +p.refunded_amount < +p.amount) {
                    <button mat-button (click)="refund(p)">Refund</button> }</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
      <h2>Invoices &amp; credit notes</h2>
      @if (!invoices().length) { <p class="muted">None on this day.</p> }
      @else {
        <table class="table" data-testid="invoices-table">
          <thead><tr><th>Number</th><th>Time</th><th>Kind</th><th class="num">Total</th><th></th></tr></thead>
          <tbody>
            @for (i of invoices(); track i.id) {
              <tr><td><b>{{ i.number }}</b></td><td>{{ i.issued_at | date: 'HH:mm' }}</td>
                <td>{{ i.kind === 'invoice' ? 'Invoice' : 'Credit note' + (i.snapshot.original_number ? ' for ' + i.snapshot.original_number : '') }}</td>
                <td class="num">{{ price(i.total) }}</td>
                <td><button mat-icon-button (click)="pdf(i)" [attr.aria-label]="'Open ' + i.number"><mat-icon>picture_as_pdf</mat-icon></button></td></tr>
            }
          </tbody>
        </table>
      }
    }
  `,
})
export class PaymentsPage implements OnInit {
  private readonly api = inject(BillingService);
  private readonly tenancy = inject(TenancyService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  private readonly auth = inject(AuthService);
  protected readonly label = METHOD_LABEL;
  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly day = signal(new Date().toLocaleDateString('en-CA'));
  protected readonly payments = signal<BillPayment[] | null>(null);
  protected readonly invoices = signal<Invoice[]>([]);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly canRefund = computed(() => this.auth.hasPermission('payments.refund'));

  protected readonly totals = computed(() => {
    const ok = (this.payments() ?? []).filter((p) => p.status === 'captured');
    const by = new Map<PayMethod, number>();
    for (const p of ok) by.set(p.method, (by.get(p.method) ?? 0) + +p.amount);
    const refunded = ok.reduce((s, p) => s + +p.refunded_amount, 0);
    const gross = ok.reduce((s, p) => s + +p.amount, 0);
    return { net: gross - refunded, refunded, byMethod: [...by.entries()].map(([method, amount]) => ({ method, amount })) };
  });

  ngOnInit(): void {
    this.tenancy.restaurantMe().subscribe({
      next: (me) => {
        const active = me.branches.filter((b) => b.is_active);
        this.branches.set(active);
        this.branchId.set((active.find((b) => b.is_primary) ?? active[0])?.id ?? null);
        this.load();
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }

  protected load(): void {
    const id = this.branchId();
    if (!id) return this.payments.set([]);
    this.payments.set(null);
    forkJoin({ p: this.api.payments(id, this.day()), i: this.api.invoices(id, this.day()) }).subscribe({
      next: ({ p, i }) => {
        this.payments.set(p);
        this.invoices.set(i);
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }

  protected price(v: string | number): string {
    return formatPrice(v);
  }

  protected refund(p: BillPayment): void {
    this.dialog
      .open(RefundDialogComponent, { data: p, width: '480px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((r) => {
        if (!r) return;
        this.snack.open('Refunded — a credit note was issued.', undefined, { duration: 3000 });
        this.load();
      });
  }

  protected pdf(i: Invoice): void {
    this.api.invoicePdf(i.id).subscribe({ next: openBlob, error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 4000 }) });
  }

  protected csv(): void {
    const rows = (this.payments() ?? []).map((p) => [
      p.created_at,
      p.table_labels.join(' '),
      p.bill_label,
      p.method,
      p.method_label || p.reference,
      p.status,
      p.amount,
      p.refunded_amount,
      p.invoice_number,
      p.received_by_name,
    ]);
    downloadCsv(
      `payments-${this.day()}.csv`,
      toCsv(['Time', 'Table', 'Bill', 'Method', 'Reference', 'Status', 'Amount', 'Refunded', 'Invoice', 'By'], rows),
    );
  }
}
