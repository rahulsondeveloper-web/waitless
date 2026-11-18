import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { Bill } from '../../../core/billing/billing.service';
import { formatPrice } from '../../../core/storefront/storefront.models';

/** Every line and charge of one bill — used in the Finish popup and on the checkout page. */
@Component({
  selector: 'wl-bill-summary',
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    :host { display: block; }
    h3 { margin: 0 0 0.5rem; font-size: 1rem; }
    ul { list-style: none; margin: 0 0 0.6rem; padding: 0; display: grid; gap: 0.35rem; }
    li, .row { display: flex; justify-content: space-between; gap: 0.75rem; }
    li small { display: block; color: var(--wl-muted, #6b6b6b); font-size: 0.78rem; }
    .rows { border-top: 1px dashed var(--wl-line); padding-top: 0.5rem; display: grid; gap: 0.25rem; }
    .saved { color: #2e7d4f; }
    .grand { font-weight: 700; font-size: 1.1rem; border-top: 1px solid var(--wl-line); padding-top: 0.4rem; margin-top: 0.2rem; }
    .due { font-weight: 700; }
  `,
  template: `
    @let b = bill();
    <h3>Bill{{ b.label ? ' · ' + b.label : '' }}{{ b.table_labels.length ? ' · Table ' + b.table_labels.join(', ') : '' }}</h3>
    <ul data-testid="bill-lines">
      @for (l of b.lines; track l.id) {
        <li>
          <span>{{ l.quantity }} × {{ l.name }}
            <small>#{{ l.order_number }}{{ l.ordered_by_name ? ' · ' + l.ordered_by_name : '' }}</small></span>
          <span>{{ price(l.line_total) }}</span>
        </li>
      }
    </ul>
    <div class="rows">
      <div class="row"><span>Food</span><span>{{ price(b.subtotal) }}</span></div>
      @if (+b.sla_discount + +b.sla_discount_after_tax > 0) {
        <div class="row saved"><span>Serving-time discount</span><span>− {{ price(+b.sla_discount + +b.sla_discount_after_tax) }}</span></div>
      }
      @if (+b.manual_discount > 0) {
        <div class="row saved"><span>Discount{{ b.manual_discount_reason ? ' (' + b.manual_discount_reason + ')' : '' }}</span><span>− {{ price(b.manual_discount) }}</span></div>
      }
      @if (+b.service_charge > 0) {
        <div class="row"><span>Service charge {{ +b.service_charge_pct }}%</span><span>{{ price(b.service_charge) }}</span></div>
      }
      @for (t of b.taxes; track t.rate) {
        @if (+t.cgst > 0 || +t.sgst > 0) {
          <div class="row"><span>CGST {{ +t.rate / 2 }}%</span><span>{{ price(t.cgst) }}</span></div>
          <div class="row"><span>SGST {{ +t.rate / 2 }}%</span><span>{{ price(t.sgst) }}</span></div>
        } @else if (+t.tax > 0) {
          <div class="row"><span>GST {{ +t.rate }}%</span><span>{{ price(t.tax) }}</span></div>
        }
      } @empty {
        <div class="row"><span>Taxes</span><span>{{ price(b.tax_total) }}</span></div>
      }
      @if (+b.booking_credit > 0) {
        <div class="row saved"><span>Booking fee already paid</span><span>− {{ price(b.booking_credit) }}</span></div>
      }
      @if (+b.round_off !== 0) { <div class="row"><span>Round off</span><span>{{ price(b.round_off) }}</span></div> }
      <div class="row grand"><span>Total</span><span data-testid="summary-total">{{ price(b.grand_total) }}</span></div>
      @if (+b.paid_total > 0 && b.status !== 'paid') {
        <div class="row"><span>Paid so far</span><span>{{ price(b.paid_total) }}</span></div>
        <div class="row due"><span>To pay</span><span>{{ price(b.due) }}</span></div>
      }
    </div>
  `,
})
export class BillSummaryComponent {
  readonly bill = input.required<Bill>();
  readonly currency = input('INR');

  protected price(v: string | number): string {
    return formatPrice(v, this.currency());
  }
}
