import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

import { ApiError } from '../../../core/http/api-error';
import { OperationsService, Permission, Role, Scope } from '../../../core/restaurant/operations.service';

export interface RoleDialogData {
  role: Role | null;
  permissions: Permission[];
}

/** Create or edit a custom role: pick permissions and whether each applies to all or only assigned branches. */
@Component({
  selector: 'wl-role-dialog',
  imports: [ReactiveFormsModule, MatDialogModule, MatFormFieldModule, MatInputModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>{{ data.role ? 'Edit role' : 'New role' }}</h2>
    <mat-dialog-content>
      <form [formGroup]="form" id="role-form" (ngSubmit)="save()" novalidate>
        <mat-form-field appearance="outline" class="full">
          <mat-label>Role name</mat-label>
          <input matInput formControlName="name" maxlength="80" cdkFocusInitial />
          <mat-error>Enter a name</mat-error>
        </mat-form-field>
        <mat-form-field appearance="outline" class="full">
          <mat-label>Description (optional)</mat-label>
          <input matInput formControlName="description" maxlength="200" />
        </mat-form-field>
      </form>
      @for (group of groups(); track group.module) {
        <fieldset>
          <legend>{{ group.module }}</legend>
          @for (p of group.items; track p.key) {
            <div class="perm">
              <label>
                <input type="checkbox" [checked]="!!chosen()[p.key]" (change)="toggle(p.key, $any($event.target).checked)" />
                {{ p.description }}
              </label>
              @if (chosen()[p.key]) {
                <select [value]="chosen()[p.key]" (change)="setScope(p.key, $any($event.target).value)"
                        [attr.aria-label]="'Scope for ' + p.description">
                  <option value="own_branches">Their branches</option>
                  <option value="all">All branches</option>
                </select>
              }
            </div>
          }
        </fieldset>
      }
      @if (error()) {
        <p class="err" role="alert">{{ error() }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="undefined">Cancel</button>
      <button mat-flat-button type="submit" form="role-form" [disabled]="saving()">Save role</button>
    </mat-dialog-actions>
  `,
  styles: `
    .full {
      width: 100%;
    }
    fieldset {
      border: 0;
      border-top: 1px solid var(--wl-line);
      padding: 0.5rem 0;
      margin: 0;
    }
    legend {
      font-weight: 600;
      text-transform: capitalize;
      padding-right: 0.5rem;
    }
    .perm {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.6rem;
      padding: 0.2rem 0;
      font-size: 0.9rem;
      label {
        display: flex;
        gap: 0.5rem;
        align-items: center;
      }
      select {
        font: inherit;
        font-size: 0.8rem;
        padding: 0.15rem 0.3rem;
      }
    }
    .err {
      color: #a3321c;
    }
  `,
})
export class RoleDialogComponent {
  protected readonly data = inject<RoleDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<RoleDialogComponent, Role>);
  private readonly ops = inject(OperationsService);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly chosen = signal<Record<string, Scope>>({ ...(this.data.role?.permissions ?? {}) });
  protected readonly form = inject(NonNullableFormBuilder).group({
    name: [this.data.role?.name ?? '', [Validators.required, Validators.minLength(2)]],
    description: [this.data.role?.description ?? ''],
  });
  /** Billing access is never delegated (backend rejects it too). */
  protected readonly groups = computed(() => {
    const by = new Map<string, Permission[]>();
    for (const p of this.data.permissions.filter((x) => x.key !== 'subscription.manage')) {
      by.set(p.module, [...(by.get(p.module) ?? []), p]);
    }
    return [...by.entries()].map(([module, items]) => ({ module, items }));
  });

  protected toggle(key: string, on: boolean): void {
    this.chosen.update((c) => {
      const next = { ...c };
      if (on) next[key] = 'own_branches';
      else delete next[key];
      return next;
    });
  }

  protected setScope(key: string, scope: Scope): void {
    this.chosen.update((c) => ({ ...c, [key]: scope }));
  }

  protected save(): void {
    if (this.form.invalid) return this.form.markAllAsTouched();
    if (!Object.keys(this.chosen()).length) {
      this.error.set('Choose at least one permission.');
      return;
    }
    const v = this.form.getRawValue();
    const body = { name: v.name.trim(), description: v.description.trim() || null, permissions: this.chosen() };
    this.saving.set(true);
    const req = this.data.role ? this.ops.updateRole(this.data.role.id, body) : this.ops.createRole(body);
    req.subscribe({
      next: (r) => this.ref.close(r),
      error: (e: ApiError) => {
        this.saving.set(false);
        this.error.set(e.message);
      },
    });
  }
}
