import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { forkJoin } from 'rxjs';

import { ApiError } from '../../../core/http/api-error';
import { FeatureDef, Plan, SuperAdminService } from '../../../core/platform-admin/super-admin.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

interface EditRow {
  def: FeatureDef;
  on: boolean;
  unlimited: boolean;
  limit: number | null;
}

/** Create or edit a plan: prices, trial, features on/off and limits (PRD §17 — no code changes). */
@Component({
  selector: 'wl-plan-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../super-admin.scss'],
  styles: `
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 0.7rem; }
    h3 { font-size: 0.95rem; margin: 1rem 0 0.4rem; }
    .feats { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 0.35rem; }
    .limit { display: grid; grid-template-columns: 1fr auto 6rem; gap: 0.5rem; align-items: center; margin-bottom: 0.35rem; }
  `,
  template: `
    <h2 mat-dialog-title>{{ data.plan ? 'Edit ' + data.plan.name : 'New plan' }}</h2>
    <mat-dialog-content>
      <form id="plan-form" (ngSubmit)="save()">
        <div class="grid">
          <label class="field"><span>Name</span><input name="n" [(ngModel)]="p.name" required data-testid="plan-name" /></label>
          <label class="field"><span>Code (cannot change later)</span>
            <input name="c" [(ngModel)]="p.code" [disabled]="!!data.plan" pattern="[a-z0-9_-]+" data-testid="plan-code" /></label>
          <label class="field"><span>Monthly price (₹)</span><input type="number" min="0" name="pm" [(ngModel)]="p.price_monthly" data-testid="plan-monthly" /></label>
          <label class="field"><span>Yearly price (₹)</span><input type="number" min="0" name="py" [(ngModel)]="p.price_yearly" /></label>
          <label class="field"><span>Free trial (days)</span><input type="number" min="0" max="90" name="t" [(ngModel)]="p.trial_days" /></label>
          <label class="field"><span>Order on the pricing page</span><input type="number" min="0" name="o" [(ngModel)]="p.sort_order" /></label>
        </div>
        <label class="field" style="margin-top: 0.7rem"><span>Description</span><input name="d" [(ngModel)]="p.description" maxlength="300" /></label>
        <label class="check"><input type="checkbox" name="pub" [(ngModel)]="p.is_public" /> Shown to restaurants when they sign up</label>
        <label class="check"><input type="checkbox" name="act" [(ngModel)]="p.is_active" /> Active (can be assigned)</label>

        <h3>Features</h3>
        <div class="feats">
          @for (r of features; track r.def.key) {
            <label class="check"><input type="checkbox" [name]="'f-' + r.def.key" [(ngModel)]="r.on" [attr.data-testid]="'feat-' + r.def.key" /> {{ r.def.label }}</label>
          }
        </div>
        <h3>Limits</h3>
        @for (r of limits; track r.def.key) {
          <div class="limit">
            <span>{{ r.def.label }}</span>
            <label class="check"><input type="checkbox" [name]="'u-' + r.def.key" [(ngModel)]="r.unlimited" /> Unlimited</label>
            <input type="number" min="0" [name]="'l-' + r.def.key" [(ngModel)]="r.limit" [disabled]="r.unlimited" [attr.aria-label]="r.def.label + ' limit'"
                   [attr.data-testid]="'limit-' + r.def.key" />
          </div>
        }
        @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="plan-form" [disabled]="busy() || !p.name.trim() || !p.code.trim()" data-testid="save-plan">Save plan</button>
    </mat-dialog-actions>
  `,
})
export class PlanDialogComponent {
  protected readonly data = inject<{ plan: Plan | null; catalog: FeatureDef[] }>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<PlanDialogComponent, Plan>);
  private readonly api = inject(SuperAdminService);
  protected p: Plan = this.data.plan
    ? { ...this.data.plan }
    : { code: '', name: '', description: '', price_monthly: '0', price_yearly: '0', currency: 'INR', trial_days: 14, is_public: true, is_active: true, sort_order: 10, features: [] };
  private readonly existing = new Map(this.p.features.map((f) => [f.key, f]));
  protected readonly features: EditRow[] = this.data.catalog
    .filter((d) => d.kind === 'feature')
    .map((def) => ({ def, on: !!this.existing.get(def.key)?.enabled, unlimited: true, limit: null }));
  protected readonly limits: EditRow[] = this.data.catalog
    .filter((d) => d.kind === 'limit')
    .map((def) => {
      const f = this.existing.get(def.key);
      return { def, on: true, unlimited: !f || f.limit === null, limit: f?.limit ?? null };
    });
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected save(): void {
    this.busy.set(true);
    this.error.set(null);
    const features = [
      ...this.features.filter((r) => r.on).map((r) => ({ key: r.def.key, enabled: true, limit: null })),
      ...this.limits.map((r) => ({ key: r.def.key, enabled: true, limit: r.unlimited ? null : Math.max(0, Math.floor(+(r.limit ?? 0))) })),
    ];
    this.api
      .savePlan({ ...this.p, code: this.p.code.trim(), price_monthly: String(this.p.price_monthly || 0), price_yearly: String(this.p.price_yearly || 0), features })
      .subscribe({
        next: (saved) => this.ref.close(saved),
        error: (e: ApiError) => {
          this.busy.set(false);
          this.error.set(e.message);
        },
      });
  }
}

/** Plans (PRD §17): what each plan includes, prices and how many restaurants use it. */
@Component({
  selector: 'wl-sa-plans',
  imports: [MatButtonModule, MatIconModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../super-admin.scss'],
  styles: `
    .plans { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; }
    .plan { display: grid; gap: 0.5rem; align-content: start; }
    .plan.off { opacity: 0.6; }
    .price { font-size: 1.4rem; font-weight: 700; }
    ul { margin: 0; padding-left: 1.1rem; }
  `,
  template: `
    <header class="page-head">
      <div><h1>Plans</h1><p class="muted">Changes apply to every restaurant on the plan immediately.</p></div>
      <button mat-flat-button (click)="edit(null)" data-testid="new-plan"><mat-icon>add</mat-icon>New plan</button>
    </header>
    @if (error(); as e) { <wl-error-state [message]="e.message" (retry)="load()" /> }
    @else if (!plans()) { <wl-loading-state /> }
    @else {
      <div class="plans">
        @for (p of plans(); track p.id) {
          <article class="panel plan" [class.off]="!p.is_active" data-testid="plan-card">
            <header><h2>{{ p.name }} <span class="muted small">{{ p.code }}</span></h2>
              @if (!p.is_active) { <span class="badge" data-tone="bad">Inactive</span> }
              @if (!p.is_public) { <span class="badge">Hidden</span> }</header>
            <p class="price">{{ +p.price_monthly ? price(p.price_monthly) + ' / month' : 'Free' }}</p>
            <p class="muted small">{{ +p.price_yearly ? price(p.price_yearly) + ' / year · ' : '' }}{{ p.trial_days }}-day trial · {{ p.subscribers }} restaurants</p>
            <ul>
              @for (f of p.features; track f.key) {
                @if (f.key.startsWith('max_')) { <li>{{ label(f.key) }}: {{ f.limit === null ? 'unlimited' : f.limit }}</li> }
                @else if (f.enabled) { <li>{{ label(f.key) }}</li> }
              }
            </ul>
            <button mat-stroked-button (click)="edit(p)" [attr.data-testid]="'edit-plan-' + p.code">Edit</button>
          </article>
        }
      </div>
    }
  `,
})
export class SaPlansPage implements OnInit {
  private readonly api = inject(SuperAdminService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  protected readonly plans = signal<Plan[] | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  private catalog: FeatureDef[] = [];

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    forkJoin({ plans: this.api.plans(), catalog: this.api.features() }).subscribe({
      next: ({ plans, catalog }) => {
        this.catalog = catalog;
        this.plans.set(plans);
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }

  protected label(key: string): string {
    return this.catalog.find((c) => c.key === key)?.label ?? key;
  }

  protected price(v: string): string {
    return formatPrice(v);
  }

  protected edit(plan: Plan | null): void {
    this.dialog
      .open(PlanDialogComponent, { data: { plan, catalog: this.catalog }, width: '760px', maxWidth: '96vw' })
      .afterClosed()
      .subscribe((saved?: Plan) => {
        if (!saved) return;
        this.snack.open(`${saved.name} saved.`, undefined, { duration: 2500 });
        this.load();
      });
  }
}
