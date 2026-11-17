import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';

import { ApiError } from '../../../core/http/api-error';
import { OperationsService, Role, Staff } from '../../../core/restaurant/operations.service';
import { Branch } from '../../../core/tenancy/tenancy.models';

export interface StaffDialogData {
  staff: Staff | null; // null = invite
  roles: Role[];
  branches: Branch[];
  fullAdmin: boolean; // owner-level: may grant manager / all branches
  myBranchIds: string[];
}

/** Invite or edit an employee. They sign in with their mobile number + one-time code. */
@Component({
  selector: 'wl-staff-dialog',
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatSlideToggleModule,
    MatButtonModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>{{ data.staff ? 'Edit ' + data.staff.full_name : 'Add an employee' }}</h2>
    <mat-dialog-content>
      <form [formGroup]="form" id="staff-form" (ngSubmit)="save()" class="form" novalidate>
        @if (!data.staff) {
          <mat-form-field appearance="outline">
            <mat-label>Full name</mat-label>
            <input matInput formControlName="full_name" cdkFocusInitial />
            <mat-error>Enter the name</mat-error>
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Mobile number</mat-label>
            <span matTextPrefix>+91&nbsp;</span>
            <input matInput type="tel" formControlName="phone" inputmode="tel" />
            <mat-hint>They sign in with this number and a one-time code.</mat-hint>
            <mat-error>Enter a valid mobile number</mat-error>
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Email (optional)</mat-label>
            <input matInput type="email" formControlName="email" />
          </mat-form-field>
        }
        <mat-form-field appearance="outline">
          <mat-label>Role</mat-label>
          <mat-select formControlName="role_id">
            @for (r of assignableRoles; track r.id) {
              <mat-option [value]="r.id">{{ r.name }}{{ r.is_system ? '' : ' (custom)' }}</mat-option>
            }
          </mat-select>
          <mat-error>Choose a role</mat-error>
        </mat-form-field>
        @if (data.fullAdmin) {
          <mat-slide-toggle formControlName="all_branches">Access to all branches</mat-slide-toggle>
        }
        @if (!form.controls.all_branches.value) {
          <fieldset>
            <legend>Branches</legend>
            @for (b of selectableBranches; track b.id) {
              <mat-checkbox [checked]="branchIds().has(b.id)" (change)="toggle(b.id, $event.checked)">{{ b.name }}</mat-checkbox>
            }
          </fieldset>
        }
      </form>
      @if (error()) {
        <p class="err" role="alert">{{ error() }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="undefined">Cancel</button>
      <button mat-flat-button type="submit" form="staff-form" [disabled]="saving()">{{ data.staff ? 'Save' : 'Add employee' }}</button>
    </mat-dialog-actions>
  `,
  styles: `
    .form {
      display: grid;
      gap: 0.2rem;
      padding-top: 0.4rem;
      min-width: min(420px, 82vw);
    }
    fieldset {
      border: 0;
      padding: 0;
      margin: 0.6rem 0 0;
      display: grid;
    }
    legend {
      font-size: 0.85rem;
      color: var(--wl-text-soft);
    }
    .err {
      color: #a3321c;
    }
  `,
})
export class StaffDialogComponent {
  protected readonly data = inject<StaffDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<StaffDialogComponent, Staff>);
  private readonly ops = inject(OperationsService);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly assignableRoles = this.data.roles.filter(
    (r) => r.key !== 'owner' && (this.data.fullAdmin || r.key !== 'manager'),
  );
  protected readonly selectableBranches = this.data.fullAdmin
    ? this.data.branches
    : this.data.branches.filter((b) => this.data.myBranchIds.includes(b.id));
  protected readonly branchIds = signal(
    new Set(this.data.staff?.branch_ids ?? (this.selectableBranches.length === 1 ? [this.selectableBranches[0].id] : [])),
  );

  protected readonly form = inject(NonNullableFormBuilder).group({
    full_name: [this.data.staff?.full_name ?? '', this.data.staff ? [] : [Validators.required, Validators.minLength(2)]],
    phone: ['', this.data.staff ? [] : [Validators.required, Validators.pattern(/^[+\d][\d\s-]{7,18}$/)]],
    email: ['', Validators.email],
    role_id: [this.data.staff?.role_id ?? '', Validators.required],
    all_branches: [this.data.staff?.all_branches ?? false],
  });

  protected toggle(id: string, on: boolean): void {
    this.branchIds.update((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  protected save(): void {
    if (this.form.invalid) return this.form.markAllAsTouched();
    const v = this.form.getRawValue();
    if (!v.all_branches && !this.branchIds().size) {
      this.error.set('Choose at least one branch.');
      return;
    }
    const branch_ids = v.all_branches ? [] : [...this.branchIds()];
    this.saving.set(true);
    const req = this.data.staff
      ? this.ops.updateStaff(this.data.staff.membership_id, { role_id: v.role_id, all_branches: v.all_branches, branch_ids })
      : this.ops.invite({
          full_name: v.full_name.trim(),
          phone: v.phone,
          email: v.email.trim() || null,
          role_id: v.role_id,
          all_branches: v.all_branches,
          branch_ids,
        });
    req.subscribe({
      next: (s) => this.ref.close(s),
      error: (e: ApiError) => {
        this.saving.set(false);
        this.error.set(e.message);
      },
    });
  }
}
