import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { OperationsService } from '../../../core/restaurant/operations.service';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/** Branches (PRD §3.2): list, open a new branch (plan limit), activate/deactivate. Address & map live in Profile. */
@Component({
  selector: 'wl-branches-page',
  imports: [ReactiveFormsModule, RouterLink, MatButtonModule, MatIconModule, MatSlideToggleModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="page-head">
      <div>
        <h1>Branches</h1>
        <p class="muted">Each branch has its own tables, staff access, hours and map location.</p>
      </div>
      @if (isOwner()) {
        <button mat-flat-button type="button" (click)="adding.set(!adding())">
          <mat-icon>add_business</mat-icon> {{ adding() ? 'Cancel' : 'New branch' }}
        </button>
      }
    </header>

    @if (adding()) {
      <form class="card add" [formGroup]="form" (ngSubmit)="create()" novalidate aria-label="New branch">
        <label>Branch name <input formControlName="name" /></label>
        <label class="wide">Street address <input formControlName="address_line" /></label>
        <label>City <input formControlName="city" /></label>
        <label>State <input formControlName="state" /></label>
        <label>PIN code <input formControlName="postal_code" /></label>
        <label>Phone <input type="tel" formControlName="phone" /></label>
        <div class="wide row">
          @if (formError()) { <p class="err" role="alert">{{ formError() }}</p> }
          <button mat-flat-button type="submit" [disabled]="saving()">Create branch</button>
        </div>
      </form>
    }

    @if (error(); as e) {
      <wl-error-state title="Could not load branches" [message]="e.message" [retryable]="false" />
    } @else if (!branches()) {
      <wl-loading-state />
    } @else {
      <ul class="grid">
        @for (b of branches(); track b.id) {
          <li class="card branch" [class.off]="!b.is_active">
            <div class="top">
              <h2>{{ b.name }}</h2>
              @if (b.is_primary) { <span class="tag">Main</span> }
            </div>
            <p>{{ b.address_line }}<br />{{ b.city }}, {{ b.state }} {{ b.postal_code }}</p>
            @if (b.phone) { <p class="muted">{{ b.phone }}</p> }
            <p class="muted small">{{ b.lat ? 'Pinned on the map' : 'No map pin yet' }} · {{ b.timezone }}</p>
            <div class="actions">
              <a mat-button routerLink="../profile">Address, map & hours</a>
              @if (isOwner() && !b.is_primary) {
                <mat-slide-toggle [checked]="b.is_active" (change)="toggle(b, $event.checked)">
                  {{ b.is_active ? 'Open' : 'Closed' }}
                </mat-slide-toggle>
              }
            </div>
          </li>
        }
      </ul>
    }
  `,
  styles: `
    .page-head {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: flex-end;
      gap: 1rem;
      margin-bottom: 1rem;
      h1 {
        font: 600 2rem/1.1 var(--wl-font-serif);
      }
    }
    .muted {
      color: var(--wl-muted);
    }
    .small {
      font-size: 0.8rem;
    }
    .card {
      background: var(--wl-surface);
      border: 1px solid var(--wl-line);
      border-radius: 14px;
      padding: 1rem 1.2rem;
    }
    .add {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.6rem 1rem;
      margin-bottom: 1rem;
      label {
        display: grid;
        gap: 0.2rem;
        font-size: 0.85rem;
      }
      input {
        font: inherit;
        padding: 0.5rem 0.6rem;
        border: 1px solid var(--wl-line);
        border-radius: 8px;
      }
    }
    .wide {
      grid-column: 1 / -1;
    }
    .row {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 1rem;
    }
    .err {
      color: #a3321c;
      margin-right: auto;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 1rem;
    }
    .branch.off {
      opacity: 0.6;
    }
    .top {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      h2 {
        font: 600 1.3rem var(--wl-font-serif);
      }
    }
    .tag {
      padding: 0 0.5rem;
      border-radius: 999px;
      background: var(--wl-primary-soft);
      color: var(--wl-primary-dark);
      font-size: 0.72rem;
    }
    .actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 0.6rem;
    }
    @media (max-width: 600px) {
      .add {
        grid-template-columns: 1fr;
      }
    }
  `,
})
export class BranchesPage implements OnInit {
  private readonly ops = inject(OperationsService);
  private readonly snack = inject(MatSnackBar);
  private readonly auth = inject(AuthService);
  protected readonly isOwner = computed(() => this.auth.activeTenant()?.permissions['branches.manage'] === 'all');
  protected readonly branches = signal<Branch[] | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly adding = signal(false);
  protected readonly saving = signal(false);
  protected readonly formError = signal<string | null>(null);
  protected readonly form = inject(NonNullableFormBuilder).group({
    name: ['', [Validators.required, Validators.minLength(2)]],
    address_line: ['', [Validators.required, Validators.minLength(5)]],
    city: ['', [Validators.required, Validators.minLength(2)]],
    state: ['', [Validators.required, Validators.minLength(2)]],
    postal_code: [''],
    phone: [''],
  });

  ngOnInit(): void {
    this.ops.branches().subscribe({ next: (b) => this.branches.set(b), error: (e: ApiError) => this.error.set(e) });
  }

  protected create(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.formError.set('Fill in name, address, city and state.');
      return;
    }
    const v = this.form.getRawValue();
    this.saving.set(true);
    this.formError.set(null);
    this.ops
      .createBranch({ ...v, country: 'India', postal_code: v.postal_code || null, phone: v.phone || null })
      .subscribe({
        next: (b) => {
          this.saving.set(false);
          this.adding.set(false);
          this.form.reset();
          this.branches.update((list) => [...(list ?? []), b]);
          this.snack.open(`${b.name} created. Set its map pin and hours in Profile.`, undefined, { duration: 4000 });
        },
        error: (e: ApiError) => {
          this.saving.set(false);
          this.formError.set(e.message);
        },
      });
  }

  protected toggle(b: Branch, active: boolean): void {
    this.ops.setBranchActive(b.id, active).subscribe({
      next: (saved) => this.branches.update((list) => (list ?? []).map((x) => (x.id === saved.id ? saved : x))),
      error: (e: ApiError) => {
        this.snack.open(e.message, 'Dismiss', { duration: 5000 });
        this.ngOnInit();
      },
    });
  }
}
