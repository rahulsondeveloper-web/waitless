import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';

import { SaasInvoice, SubscriptionRow, Usage } from '../../../core/analytics/analytics.service';
import { ApiError } from '../../../core/http/api-error';
import { Plan, SuperAdminService } from '../../../core/platform-admin/super-admin.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

const STATUS: Record<string, { label: string; tone: string }> = {
  trialing: { label: 'Trial', tone: '' },
  active: { label: 'Active', tone: 'ok' },
  past_due: { label: 'Payment due', tone: 'warn' },
  cancelled: { label: 'Cancelled', tone: 'bad' },
  expired: { label: 'Expired', tone: 'bad' },
};

/** Assign / upgrade / downgrade a plan — immediately, with usage shown so a downgrade is a conscious choice. */
@Component({
  selector: 'wl-assign-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../super-admin.scss'],
  template: `
    <h2 mat-dialog-title>Plan for {{ data.row.tenant_name }}</h2>
    <mat-dialog-content>
      <form id="assign-form" (ngSubmit)="save()" style="display: grid; gap: 0.7rem">
        <p class="muted">Now: {{ data.row.plan_name }} ({{ data.row.status }}). The change applies immediately.</p>
        @if (usage(); as u) {
          <p class="muted small">In use: @for (l of u.limits; track l.key) { {{ l.label }} {{ l.used }}{{ $last ? '' : ' · ' }} }</p>
        }
        <label class="field"><span>Plan</span>
          <select name="p" [(ngModel)]="planId" data-testid="assign-plan">
            @for (p of data.plans; track p.id) { <option [value]="p.id">{{ p.name }} · {{ +p.price_monthly ? price(p.price_monthly) + '/month' : 'free' }}</option> }
          </select></label>
        <label class="field"><span>Billing</span>
          <select name="c" [(ngModel)]="cycle"><option value="monthly">Monthly</option><option value="yearly">Yearly</option></select></label>
        <label class="check"><input type="checkbox" name="t" [(ngModel)]="trial" /> Start with the plan's free trial</label>
        <label class="check"><input type="checkbox" name="w" [(ngModel)]="waive" [disabled]="trial" /> No invoice for the first period</label>
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="assign-form" [disabled]="busy() || !planId" data-testid="assign-save">Change plan</button>
    </mat-dialog-actions>
  `,
})
export class AssignDialogComponent implements OnInit {
  protected readonly data = inject<{ row: SubscriptionRow; plans: Plan[] }>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<AssignDialogComponent, SubscriptionRow>);
  private readonly api = inject(SuperAdminService);
  protected planId = this.data.row.plan_id;
  protected cycle = this.data.row.billing_cycle;
  protected trial = false;
  protected waive = false;
  protected readonly usage = signal<Usage | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  ngOnInit(): void {
    this.api.usage(this.data.row.tenant_id).subscribe((u) => this.usage.set(u));
  }

  protected price(v: string): string {
    return formatPrice(v);
  }

  protected save(): void {
    this.busy.set(true);
    this.api.assign(this.data.row.tenant_id, { plan_id: this.planId, billing_cycle: this.cycle, trial: this.trial, waive_first_invoice: this.waive }).subscribe({
      next: (r) => this.ref.close(r),
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}

/** Subscriptions & WaitLess invoices (PRD §16–17): renewals, upgrades, expired plans, payments. */
@Component({
  selector: 'wl-sa-subscriptions',
  imports: [DatePipe, FormsModule, MatButtonModule, MatIconModule, MatMenuModule, MatTabsModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../super-admin.scss'],
  template: `
    <header class="page-head">
      <div><h1>Subscriptions</h1><p class="muted">Plans, renewals and WaitLess invoices — separate from restaurant bills.</p></div>
      <button mat-stroked-button (click)="runRenewals()" data-testid="run-renewals"><mat-icon>autorenew</mat-icon>Run renewals now</button>
    </header>
    <mat-tab-group animationDuration="150ms" mat-stretch-tabs="false">
      <mat-tab label="Subscriptions">
        <div class="bar">
          <label class="field"><span>Show</span>
            <select [(ngModel)]="status" (ngModelChange)="load()" data-testid="sub-filter">
              <option value="">All</option><option value="trialing">On trial</option><option value="active">Active</option>
              <option value="past_due">Payment due</option><option value="expiring">Ending within 7 days</option>
              <option value="expired">Expired</option><option value="cancelled">Cancelled</option>
            </select></label>
          <label class="field grow"><span>Search</span><input type="search" [(ngModel)]="q" (keyup.enter)="load()" placeholder="Restaurant name" /></label>
        </div>
        @if (error(); as e) { <wl-error-state [message]="e.message" (retry)="load()" /> }
        @else if (!rows()) { <wl-loading-state /> }
        @else {
          <div class="scroll">
            <table class="table" data-testid="subs-table">
              <thead><tr><th>Restaurant</th><th>Plan</th><th>Status</th><th>Period ends</th><th class="num">Due</th><th></th></tr></thead>
              <tbody>
                @for (s of rows(); track s.id) {
                  <tr data-testid="sub-row">
                    <td><b>{{ s.tenant_name }}</b><br /><small class="muted">/r/{{ s.tenant_slug }} · {{ s.tenant_status }}</small></td>
                    <td>{{ s.plan_name }}<br /><small class="muted">{{ s.billing_cycle }} · {{ +s.price ? price(s.price) : 'free' }}</small></td>
                    <td><span class="badge" [attr.data-tone]="st[s.status].tone">{{ st[s.status].label }}</span>
                      @if (!s.auto_renew && (s.status === 'active' || s.status === 'trialing')) { <br /><small class="muted">won't renew</small> }</td>
                    <td>{{ s.current_period_end | date: 'd MMM y' }}
                      @if (s.status === 'past_due' && s.grace_ends_at) { <br /><small class="muted">expires {{ s.grace_ends_at | date: 'd MMM' }}</small> }</td>
                    <td class="num">{{ s.invoices_due ? price(s.amount_due) : '—' }}</td>
                    <td>
                      <button mat-stroked-button (click)="assign(s)" data-testid="change-plan">Change plan</button>
                      <button mat-icon-button [matMenuTriggerFor]="m" aria-label="More"><mat-icon>more_vert</mat-icon></button>
                      <mat-menu #m="matMenu">
                        <button mat-menu-item (click)="act(s, 'renew')">Invoice the next period now</button>
                        <button mat-menu-item (click)="extend(s)">Add free days…</button>
                        @if (s.auto_renew) { <button mat-menu-item (click)="act(s, 'stop_renewal')">Stop auto-renewal</button> }
                        @else { <button mat-menu-item (click)="act(s, 'resume_renewal')">Resume auto-renewal</button> }
                        <button mat-menu-item (click)="act(s, 'cancel')">Cancel now</button>
                      </mat-menu>
                    </td>
                  </tr>
                } @empty { <tr><td colspan="6" class="muted">No subscriptions match.</td></tr> }
              </tbody>
            </table>
          </div>
        }
      </mat-tab>

      <mat-tab label="Invoices">
        <div class="bar">
          <label class="field"><span>Show</span>
            <select [(ngModel)]="invStatus" (ngModelChange)="loadInvoices()">
              <option value="">All</option><option value="due">Unpaid</option><option value="paid">Paid</option><option value="void">Void</option>
            </select></label>
          <span class="grow"></span>
          <form class="bar" (ngSubmit)="newInvoice()" style="margin: 0">
            <label class="field"><span>Restaurant</span>
              <select name="t" [(ngModel)]="newTenant">
                <option value="">Choose…</option>
                @for (s of rows() ?? []; track s.tenant_id) { <option [value]="s.tenant_id">{{ s.tenant_name }}</option> }
              </select></label>
            <label class="field"><span>Amount (₹, before GST)</span><input type="number" min="1" name="a" [(ngModel)]="newAmount" style="width: 8rem" /></label>
            <label class="field"><span>For</span><input name="d" [(ngModel)]="newDesc" maxlength="200" placeholder="e.g. Onboarding" /></label>
            <button mat-flat-button type="submit" [disabled]="!newTenant || !(+newAmount > 0) || !newDesc.trim()">Create invoice</button>
          </form>
        </div>
        <div class="scroll">
          <table class="table" data-testid="saas-invoices-table">
            <thead><tr><th>Number</th><th>Restaurant</th><th>For</th><th>Due date</th><th class="num">Total</th><th>Status</th><th></th></tr></thead>
            <tbody>
              @for (i of invoices(); track i.id) {
                <tr>
                  <td><b>{{ i.number }}</b></td><td>{{ i.tenant_name }}</td>
                  <td>{{ i.description }}@if (i.period_start) { <br /><small class="muted">{{ i.period_start | date: 'd MMM' }} – {{ i.period_end | date: 'd MMM y' }}</small> }</td>
                  <td>{{ i.due_date | date: 'd MMM y' }}</td>
                  <td class="num">{{ price(i.total) }}<br /><small class="muted">{{ price(i.amount) }} + GST {{ price(i.tax) }}</small></td>
                  <td><span class="badge" [attr.data-tone]="i.status === 'paid' ? 'ok' : i.status === 'due' ? 'warn' : 'bad'">{{ i.status === 'due' ? 'Unpaid' : i.status }}</span>
                    @for (p of i.payments; track p.id) { @if (p.status === 'captured') { <br /><small class="muted">{{ p.method }} {{ p.reference }}</small> } }</td>
                  <td>@if (i.status === 'due') {
                    <button mat-stroked-button (click)="recordPayment(i)" data-testid="record-payment">Record payment</button>
                    <button mat-button (click)="voidInvoice(i)">Void</button> }</td>
                </tr>
              } @empty { <tr><td colspan="7" class="muted">No invoices.</td></tr> }
            </tbody>
          </table>
        </div>
      </mat-tab>
    </mat-tab-group>
  `,
})
export class SaSubscriptionsPage implements OnInit {
  private readonly api = inject(SuperAdminService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  protected readonly st = STATUS;
  protected readonly rows = signal<SubscriptionRow[] | null>(null);
  protected readonly invoices = signal<SaasInvoice[]>([]);
  protected readonly error = signal<ApiError | null>(null);
  protected status = '';
  protected q = '';
  protected invStatus = 'due';
  protected newTenant = '';
  protected newAmount: string | number = '';
  protected newDesc = '';
  private plans: Plan[] = [];

  ngOnInit(): void {
    this.api.plans().subscribe((p) => (this.plans = p.filter((x) => x.is_active)));
    this.load();
    this.loadInvoices();
  }

  protected load(): void {
    this.api.subscriptions(this.status || undefined, this.q || undefined).subscribe({ next: (r) => this.rows.set(r), error: (e: ApiError) => this.error.set(e) });
  }

  protected loadInvoices(): void {
    this.api.invoices({ status: this.invStatus || undefined }).subscribe((i) => this.invoices.set(i));
  }

  protected price(v: string): string {
    return formatPrice(v);
  }

  private done = (msg: string) => () => {
    this.snack.open(msg, undefined, { duration: 2500 });
    this.load();
    this.loadInvoices();
  };
  private fail = (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 });

  protected assign(s: SubscriptionRow): void {
    this.dialog
      .open(AssignDialogComponent, { data: { row: s, plans: this.plans }, width: '520px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((r?: SubscriptionRow) => r && this.done(`${r.tenant_name} is now on ${r.plan_name}.`)());
  }

  protected act(s: SubscriptionRow, action: string): void {
    if (action === 'cancel' && !confirm(`Cancel ${s.tenant_name}'s ${s.plan_name} plan now? Paid features stop immediately.`)) return;
    this.api.subAction(s.id, action).subscribe({ next: this.done('Done.'), error: this.fail });
  }

  protected extend(s: SubscriptionRow): void {
    const days = Number(prompt(`Add how many free days to ${s.tenant_name}?`, '14'));
    if (!days) return;
    this.api.subAction(s.id, 'extend', days).subscribe({ next: this.done(`${days} days added.`), error: this.fail });
  }

  protected runRenewals(): void {
    this.api.runRenewals().subscribe({
      next: (c) => this.done(`Renewals: ${c['renewed']} renewed, ${c['invoiced']} invoiced, ${c['expired']} expired, ${c['ended']} ended.`)(),
      error: this.fail,
    });
  }

  protected recordPayment(i: SaasInvoice): void {
    const method = prompt(`How was ${i.number} (${this.price(i.total)}) paid? bank / upi / card / cash / waived`, 'bank')?.trim().toLowerCase();
    if (!method) return;
    const reference = method === 'waived' ? 'Waived' : (prompt('Reference (UTR, cheque no.)', '') ?? '');
    this.api.recordPayment(i.id, method, reference).subscribe({ next: this.done(`${i.number} marked paid.`), error: this.fail });
  }

  protected voidInvoice(i: SaasInvoice): void {
    const reason = prompt(`Why void ${i.number}?`)?.trim();
    if (!reason) return;
    this.api.voidInvoice(i.id, reason).subscribe({ next: this.done(`${i.number} voided.`), error: this.fail });
  }

  protected newInvoice(): void {
    this.api.createInvoice(this.newTenant, String(this.newAmount), this.newDesc).subscribe({
      next: (inv) => {
        this.newAmount = '';
        this.newDesc = '';
        this.done(`${inv.number} created.`)();
      },
      error: this.fail,
    });
  }
}
