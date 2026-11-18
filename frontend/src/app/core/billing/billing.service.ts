import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';

/** Restaurant billing & POS (PRD §9) — separate from the WaitLess subscription billing. */

export type PayMethod = 'cash' | 'upi' | 'card' | 'gateway' | 'other';
export const METHOD_LABEL: Record<PayMethod, string> = {
  cash: 'Cash',
  upi: 'UPI',
  card: 'Card',
  gateway: 'Online',
  other: 'Other',
};

export interface BillLine {
  id: string;
  order_id: string;
  order_item_id: string;
  order_number: string;
  name: string;
  quantity: number;
  unit_price: string;
  line_total: string;
  tax_pct: string;
  sla_pct: string;
  sla_discount: string;
  manual_discount: string;
  taxable: string;
  ordered_by_name: string | null; // screens only, never on the invoice
}

export interface BillPayment {
  id: string;
  bill_id: string;
  method: PayMethod;
  method_label: string;
  amount: string;
  tendered: string | null;
  change_due: string;
  status: 'pending' | 'captured' | 'failed';
  reference: string;
  refunded_amount: string;
  received_by_name: string | null;
  created_at: string;
  captured_at: string | null;
  bill_label: string | null;
  table_labels: string[];
  invoice_number: string | null;
}

export interface InvoiceRef {
  id: string;
  number: string;
  kind: 'invoice' | 'credit_note';
  total: string;
  issued_at: string;
}

export interface TaxRow {
  rate: string;
  taxable: string;
  tax: string;
  cgst: string;
  sgst: string;
}

export interface Bill {
  id: string;
  branch_id: string;
  table_session_id: string;
  session_code: string;
  table_labels: string[];
  guest_name: string | null;
  sequence: number;
  label: string;
  status: 'open' | 'paid' | 'void';
  locked: boolean;
  merged_into_id: string | null;
  lines: BillLine[];
  subtotal: string;
  sla_discount: string;
  sla_discount_after_tax: string;
  manual_discount: string;
  manual_discount_pct: string | null;
  manual_discount_reason: string | null;
  taxable: string;
  service_charge_pct: string;
  service_charge: string;
  tax_total: string;
  taxes: TaxRow[];
  booking_credit: string;
  round_off: string;
  grand_total: string;
  paid_total: string;
  refunded_total: string;
  due: string;
  unserved_orders: number;
  payments: BillPayment[];
  refunds: { id: string; payment_id: string; amount: string; reason: string; created_at: string }[];
  invoices: InvoiceRef[];
  methods: PayMethod[];
  other_method_label: string;
  created_at: string;
  paid_at: string | null;
}

export interface SessionBills {
  session_id: string;
  session_code: string;
  session_status: 'open' | 'finished' | 'closed';
  branch_id: string;
  table_labels: string[];
  guest_name: string | null;
  party_size: number;
  opened_at: string;
  bills: Bill[];
  total_due: string;
  can_close: boolean;
  restaurant_name: string;
  upi_id: string;
  upi_payee_name: string;
}

export interface ActiveTable {
  session_id: string;
  session_code: string;
  session_status: 'open' | 'finished';
  table_labels: string[];
  guest_name: string | null;
  party_size: number;
  opened_at: string;
  orders: number;
  total: string;
  due: string;
  bills: number;
  paid: boolean;
}

export interface BillingSettings {
  service_charge_pct: string;
  service_charge_tax_pct: string;
  tax_split: 'cgst_sgst' | 'single';
  round_off: boolean;
  invoice_prefix: string;
  legal_name: string;
  gstin: string;
  address: string;
  invoice_footer: string;
  methods: PayMethod[];
  other_method_label: string;
  upi_id: string;
  upi_payee_name: string;
}

export interface Invoice {
  id: string;
  bill_id: string;
  number: string;
  kind: 'invoice' | 'credit_note';
  total: string;
  issued_at: string;
  original_invoice_id: string | null;
  snapshot: { bill: Bill; reason?: string | null; original_number?: string | null };
}

export interface MyInvoice {
  id: string;
  number: string;
  kind: 'invoice' | 'credit_note';
  total: string;
  issued_at: string;
  restaurant_name: string | null;
  restaurant_slug: string | null;
  items: string[];
}

/** upi://pay link for the restaurant's own UPI ID (opens any UPI app; also encoded in the QR). */
export function upiLink(vpa: string, payee: string, amount: string | number, note: string): string {
  const q = new URLSearchParams({ pa: vpa, pn: payee, am: (+amount).toFixed(2), cu: 'INR', tn: note.slice(0, 50) });
  return `upi://pay?${q.toString()}`;
}

export interface OnlinePayment {
  payment_id: string;
  provider: string;
  order_id: string;
  amount: string;
  currency: string;
  checkout: { url?: string } & Record<string, unknown>;
}

/** Equal shares of `due` for `people` payers, in paise, the last one taking the remainder. */
export function equalShares(due: string | number, people: number): string[] {
  const paise = Math.round(+due * 100);
  const n = Math.max(1, Math.floor(people));
  const each = Math.floor(paise / n);
  return Array.from({ length: n }, (_, i) => ((i === n - 1 ? paise - each * (n - 1) : each) / 100).toFixed(2));
}

@Injectable({ providedIn: 'root' })
export class BillingService {
  private readonly api = inject(ApiService);

  // ---------- staff ----------
  settings(): Observable<BillingSettings> {
    return this.api.get('restaurant/billing-settings');
  }
  saveSettings(s: BillingSettings): Observable<BillingSettings> {
    return this.api.put('restaurant/billing-settings', s);
  }
  tables(branchId: string): Observable<ActiveTable[]> {
    return this.api.get('restaurant/billing/tables', { branch_id: branchId });
  }
  sessionBills(sessionId: string): Observable<SessionBills> {
    return this.api.post(`restaurant/table-sessions/${sessionId}/bill`, {});
  }
  reopen(sessionId: string): Observable<SessionBills> {
    return this.api.post(`restaurant/table-sessions/${sessionId}/reopen`, {});
  }
  close(sessionId: string): Observable<unknown> {
    return this.api.post(`restaurant/table-sessions/${sessionId}/close`, {});
  }
  split(billId: string, orderItemIds: string[]): Observable<SessionBills> {
    return this.api.post(`restaurant/bills/${billId}/split`, { order_item_ids: orderItemIds });
  }
  merge(billId: string, sourceBillId: string): Observable<Bill> {
    return this.api.post(`restaurant/bills/${billId}/merge`, { source_bill_id: sourceBillId });
  }
  discount(billId: string, body: { pct?: string | null; amount?: string | null; reason: string }): Observable<Bill> {
    return this.api.post(`restaurant/bills/${billId}/discount`, body);
  }
  void(billId: string, reason: string): Observable<Bill> {
    return this.api.post(`restaurant/bills/${billId}/void`, { reason });
  }
  pay(
    billId: string,
    body: { method: PayMethod; amount: string; tendered?: string | null; reference?: string; method_label?: string },
    key: string,
  ): Observable<Bill> {
    return this.api.post(`restaurant/bills/${billId}/payments`, body, { 'Idempotency-Key': key });
  }
  settle(billId: string): Observable<Bill> {
    return this.api.post(`restaurant/bills/${billId}/settle`, {});
  }
  refund(paymentId: string, amount: string, reason: string, key: string): Observable<Bill> {
    return this.api.post(`restaurant/payments/${paymentId}/refunds`, { amount, reason }, { 'Idempotency-Key': key });
  }
  payments(branchId: string, date?: string): Observable<BillPayment[]> {
    return this.api.get('restaurant/payments', { branch_id: branchId, date });
  }
  bills(branchId: string, date?: string): Observable<Bill[]> {
    return this.api.get('restaurant/bills', { branch_id: branchId, date });
  }
  invoices(branchId: string, date?: string): Observable<Invoice[]> {
    return this.api.get('restaurant/invoices', { branch_id: branchId, date });
  }
  /** The PDF needs the staff bearer token, so it is fetched as a blob and opened locally. */
  invoicePdf(invoiceId: string, receipt = false): Observable<Blob> {
    return this.api.getBlob(`restaurant/invoices/${invoiceId}/pdf`, { format: receipt ? 'receipt' : 'a4' });
  }

  // ---------- guests (table token) ----------
  guestBills(token: string): Observable<SessionBills> {
    return this.api.getWithHeaders('table-session/bills', { 'X-Table-Token': token });
  }
  finish(token: string): Observable<SessionBills> {
    return this.api.post('table-session/finish', {}, { 'X-Table-Token': token });
  }
  payOnline(token: string, billId: string): Observable<OnlinePayment> {
    return this.api.post(`table-session/bills/${billId}/pay`, {}, { 'X-Table-Token': token });
  }
  mockPay(token: string, orderId: string, success: boolean): Observable<{ result: string }> {
    return this.api.post(`public/payments/mock-bill/${encodeURIComponent(orderId)}`, { success }, { 'X-Table-Token': token });
  }
  /** "I paid the restaurant's UPI ID" — waits for staff to confirm. */
  upiClaim(token: string, billId: string, reference: string): Observable<SessionBills> {
    return this.api.post(`table-session/bills/${billId}/upi-claim`, { reference }, { 'X-Table-Token': token });
  }
  confirmUpi(paymentId: string): Observable<Bill> {
    return this.api.post(`restaurant/payments/${paymentId}/confirm`, {});
  }
  rejectUpi(paymentId: string): Observable<Bill> {
    return this.api.post(`restaurant/payments/${paymentId}/reject`, {});
  }
  // ---------- signed-in customer ----------
  myInvoices(): Observable<MyInvoice[]> {
    return this.api.get('me/invoices');
  }
  myInvoicePdf(id: string): Observable<Blob> {
    return this.api.getBlob(`me/invoices/${id}/pdf`);
  }
  guestReceiptUrl(token: string, invoiceId: string): string {
    return `/api/v1/table-session/invoices/${invoiceId}/pdf?t=${encodeURIComponent(token)}`;
  }
}

export function openBlob(blob: Blob): void {
  const url = URL.createObjectURL(blob);
  window.open(url, '_blank', 'noopener');
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
