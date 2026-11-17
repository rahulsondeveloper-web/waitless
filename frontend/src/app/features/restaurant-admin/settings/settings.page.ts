import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { RouterLink } from '@angular/router';

import { AnalyticsService, SaasInvoice, Ticket, Usage } from '../../../core/analytics/analytics.service';
import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { CheckoutService } from '../../../core/payments/checkout.service';

const STATUS: Record<string, string> = {
  trialing: 'Free trial',
  active: 'Active',
  past_due: 'Payment due',
  cancelled: 'Cancelled',
  expired: 'Expired',
};

/** Restaurant settings: the WaitLess plan & invoices, manager limits, and help requests to WaitLess. */
@Component({
  selector: 'wl-settings-page',
  imports: [DatePipe, FormsModule, RouterLink, MatButtonModule, MatIconModule, MatTabsModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../admin-bookings.scss', '../inventory/inventory-forms.scss'],
  styles: `
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; margin-top: 1rem; }
    .panel h2 { margin: 0 0 0.6rem; font-size: 1.05rem; }
    .big { font-size: 1.5rem; font-weight: 700; margin: 0; }
    .meter { display: grid; gap: 0.2rem; margin-bottom: 0.7rem; }
    .meter .track { height: 8px; border-radius: 999px; background: var(--wl-line); overflow: hidden; }
    .meter .fill { height: 100%; background: var(--wl-primary); }
    .meter .fill.full { background: #c0442b; }
    .feats { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.25rem; }
    .feats li { display: flex; gap: 0.4rem; align-items: center; }
    .feats .off { color: var(--wl-muted); }
    .warn { background: #fff4dc; border: 1px solid #e0a53b; border-radius: 10px; padding: 0.6rem 0.8rem; }
    .mock { display: flex; gap: 0.4rem; align-items: center; }
    .tickets { list-style: none; padding: 0; display: grid; gap: 0.5rem; }
    .tickets li { border: 1px solid var(--wl-line); border-radius: 10px; padding: 0.6rem 0.8rem; }
  `,
  template: `
    <header class="page-head"><div><h1>Settings</h1><p class="muted">Your WaitLess plan, approval limits and help.</p></div></header>
    <mat-tab-group animationDuration="150ms" mat-stretch-tabs="false">
      <mat-tab label="Plan & invoices">
        @if (error(); as e) { <wl-error-state [message]="e.message" (retry)="load()" /> }
        @else if (!usage()) { <wl-loading-state /> }
        @else {
          @let u = usage()!;
          <div class="grid">
            <section class="panel" data-testid="plan-panel">
              <h2>Your plan</h2>
              @if (u.subscription; as s) {
                <p class="big">{{ s.plan_name }}</p>
                <p class="muted">{{ status[s.status] }} ·
                  @if (s.status === 'trialing') { trial ends {{ s.trial_ends_at | date: 'mediumDate' }} }
                  @else { {{ +s.price > 0 ? price(s.price) + ' / ' + (s.billing_cycle === 'yearly' ? 'year' : 'month') + ' · ' : '' }}
                    {{ s.auto_renew ? 'renews' : 'ends' }} {{ s.current_period_end | date: 'mediumDate' }} }</p>
                @if (s.status === 'past_due') {
                  <p class="warn">Payment due — paid features stop on {{ s.grace_ends_at | date: 'mediumDate' }} unless the invoice below is paid.</p>
                }
              } @else {
                <p class="warn">No active WaitLess plan. Paid features are switched off — contact WaitLess to choose a plan.</p>
              }
              <p class="muted">Last 30 days: {{ u.last_30_days.orders }} orders · {{ price(u.last_30_days.sales) }} sales · {{ u.last_30_days.reservations }} bookings</p>
            </section>
            <section class="panel">
              <h2>Usage</h2>
              @for (l of u.limits; track l.key) {
                <div class="meter" [attr.data-testid]="'usage-' + l.key">
                  <span>{{ l.label }}: <b>{{ l.used }}</b> of {{ l.limit === null ? 'unlimited' : l.limit }}</span>
                  @if (l.limit !== null) {
                    <div class="track" role="progressbar" [attr.aria-valuenow]="l.used" [attr.aria-valuemax]="l.limit">
                      <div class="fill" [class.full]="l.used >= l.limit" [style.width.%]="l.limit ? (100 * l.used) / l.limit : 100"></div></div>
                  }
                </div>
              }
            </section>
            <section class="panel">
              <h2>Included</h2>
              <ul class="feats">
                @for (f of u.features; track f.key) {
                  <li [class.off]="!f.enabled"><mat-icon inline>{{ f.enabled ? 'check_circle' : 'remove_circle_outline' }}</mat-icon>{{ f.label }}</li>
                }
              </ul>
            </section>
          </div>

          @if (canPay()) {
            <section class="panel" style="margin-top: 1rem">
              <h2>WaitLess invoices</h2>
              @if (!invoices().length) { <p class="muted">No invoices yet.</p> }
              @else {
                <table class="table" data-testid="saas-invoices">
                  <thead><tr><th>Number</th><th>For</th><th>Due</th><th class="num">Total</th><th>Status</th><th></th></tr></thead>
                  <tbody>
                    @for (i of invoices(); track i.id) {
                      <tr>
                        <td><b>{{ i.number }}</b></td>
                        <td>{{ i.description }}@if (i.period_start) { <br /><small class="muted">{{ i.period_start | date: 'd MMM' }} – {{ i.period_end | date: 'd MMM y' }}</small> }</td>
                        <td>{{ i.due_date | date: 'd MMM y' }}</td>
                        <td class="num">{{ price(i.total) }}<br /><small class="muted">incl. GST {{ +i.tax_pct }}%</small></td>
                        <td>{{ i.status === 'due' ? 'To pay' : i.status === 'paid' ? 'Paid ' + (i.paid_at | date: 'd MMM') : 'Void' }}</td>
                        <td>
                          @if (i.status === 'due') {
                            @if (paying()?.id === i.id) {
                              <span class="mock"><small class="muted">Test payment</small>
                                <button mat-flat-button (click)="mockPay(true)" data-testid="saas-mock-pay">Pay now</button>
                                <button mat-button (click)="mockPay(false)">Fail</button></span>
                            } @else {
                              <button mat-flat-button (click)="pay(i)" data-testid="saas-pay">Pay {{ price(i.total) }}</button>
                            }
                          }
                        </td>
                      </tr>
                    }
                  </tbody>
                </table>
              }
            </section>
          }
        }
      </mat-tab>

      <mat-tab label="Approval limits">
        <form class="form panel" style="max-width: 560px; margin-top: 1rem" (ngSubmit)="saveLimits()">
          <p class="hint">What managers can do without you. Owners have no limit. Cashiers cannot give discounts or refunds.</p>
          <div class="grid2">
            <label class="field"><span>Largest manual discount (%)</span>
              <input type="number" min="0" max="100" step="0.5" name="d" [(ngModel)]="limits.manual_discount_pct" [disabled]="!canSettings()" data-testid="limit-discount" /></label>
            <label class="field"><span>Largest refund (₹)</span>
              <input type="number" min="0" step="100" name="r" [(ngModel)]="limits.refund_amount" [disabled]="!canSettings()" /></label>
          </div>
          @if (canSettings()) { <div class="save"><button mat-flat-button type="submit" data-testid="save-limits">Save</button></div> }
          <p class="hint">Service charge, GST display and invoice details are under <a routerLink="../billing">Billing → Settings</a>.
            The serving-time promise is under <a routerLink="../discounts">Discount settings</a>.</p>
        </form>
      </mat-tab>

      <mat-tab label="Help">
        <div class="grid">
          <form class="form panel" (ngSubmit)="ask()">
            <h2>Ask WaitLess for help</h2>
            <label class="field"><span>Topic</span>
              <select name="t" [(ngModel)]="topic">
                <option value="general">General question</option><option value="technical">Something is not working</option>
                <option value="billing">Plan or invoice</option><option value="complaint">Complaint</option><option value="other">Other</option>
              </select></label>
            <label class="field"><span>Message</span>
              <textarea name="m" [(ngModel)]="message" maxlength="4000" rows="5" placeholder="What happened, and when?" data-testid="help-message"></textarea></label>
            <div class="save"><button mat-flat-button type="submit" [disabled]="message.trim().length < 10" data-testid="help-send">Send</button></div>
          </form>
          <section class="panel">
            <h2>Your requests</h2>
            <ul class="tickets" data-testid="help-list">
              @for (t of tickets(); track t.id) {
                <li><b>{{ topicLabel(t.topic) }}</b> · <span class="muted">{{ t.created_at | date: 'd MMM, HH:mm' }}</span>
                  <span class="badge" [attr.data-status]="t.status === 'resolved' || t.status === 'closed' ? 'seated' : 'waiting'">{{ t.status.replace('_', ' ') }}</span>
                  <p>{{ t.message }}</p></li>
              } @empty { <li class="muted">No requests yet.</li> }
            </ul>
          </section>
        </div>
      </mat-tab>
    </mat-tab-group>
  `,
})
export class SettingsPage implements OnInit {
  private readonly api = inject(AnalyticsService);
  private readonly auth = inject(AuthService);
  private readonly snack = inject(MatSnackBar);
  private readonly checkout = inject(CheckoutService);
  protected readonly status = STATUS;
  protected readonly usage = signal<Usage | null>(null);
  protected readonly invoices = signal<SaasInvoice[]>([]);
  protected readonly tickets = signal<Ticket[]>([]);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly paying = signal<{ id: string; orderId: string } | null>(null);
  protected readonly canPay = computed(() => this.auth.hasPermission('subscription.manage'));
  protected readonly canSettings = computed(() => this.auth.hasPermission('settings.manage'));
  protected limits = { manual_discount_pct: '10', refund_amount: '2000' };
  protected topic = 'general';
  protected message = '';

  ngOnInit(): void {
    this.load();
    this.api.limits().subscribe((l) => (this.limits = { ...l }));
    this.api.tickets().subscribe((t) => this.tickets.set(t));
  }

  protected load(): void {
    this.error.set(null);
    this.api.usage().subscribe({ next: (u) => this.usage.set(u), error: (e: ApiError) => this.error.set(e) });
    if (this.canPay()) this.api.invoices().subscribe((i) => this.invoices.set(i));
  }

  protected price(v: string | number): string {
    return formatPrice(v);
  }

  protected topicLabel(t: string): string {
    return { general: 'Question', technical: 'Not working', billing: 'Plan / invoice', complaint: 'Complaint', other: 'Other' }[t] ?? t;
  }

  protected pay(i: SaasInvoice): void {
    this.api.payInvoice(i.id).subscribe({
      next: (r) => {
        if (r.checkout.url) {
          this.paying.set({ id: i.id, orderId: r.order_id });
          return;
        }
        void this.checkout.open(r.checkout, { name: 'WaitLess', description: `Invoice ${i.number}` }).then((res) => {
          if (res === 'submitted') setTimeout(() => this.load(), 3000);
          else if (res === 'unavailable') this.snack.open('The payment window could not open. Please try again.', 'OK', { duration: 5000 });
        });
      },
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 }),
    });
  }

  protected mockPay(success: boolean): void {
    const p = this.paying();
    if (!p) return;
    this.api.mockPay(p.orderId, success).subscribe({
      next: (r) => {
        this.paying.set(null);
        this.snack.open(r.result === 'paid' ? 'Paid — thank you!' : 'The payment did not go through.', undefined, { duration: 3000 });
        this.load();
      },
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 }),
    });
  }

  protected saveLimits(): void {
    this.api.saveLimits({ manual_discount_pct: String(this.limits.manual_discount_pct), refund_amount: String(this.limits.refund_amount) }).subscribe({
      next: (l) => {
        this.limits = { ...l };
        this.snack.open('Limits saved.', undefined, { duration: 2000 });
      },
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 }),
    });
  }

  protected ask(): void {
    this.api.askHelp(this.topic, this.message).subscribe({
      next: () => {
        this.message = '';
        this.snack.open('Sent — WaitLess will get back to you.', undefined, { duration: 3000 });
        this.api.tickets().subscribe((t) => this.tickets.set(t));
      },
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 }),
    });
  }
}
