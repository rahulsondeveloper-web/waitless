import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

import { ApiError } from '../../../core/http/api-error';
import { AdminCategory, AdminMealType, AdminMenu, MenuService } from '../../../core/restaurant/menu.service';

export interface CategoryDialogData {
  category: AdminCategory | null;
  mealTypes: AdminMealType[];
  defaultMealTypeId: string | null;
}

/** Create / rename a category and choose which meal-type menus it appears on. Closes with the new menu. */
@Component({
  selector: 'wl-category-dialog',
  imports: [ReactiveFormsModule, MatDialogModule, MatFormFieldModule, MatInputModule, MatCheckboxModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>{{ data.category ? 'Edit category' : 'New category' }}</h2>
    <mat-dialog-content>
      <form [formGroup]="form" id="cat-form" (ngSubmit)="save()" novalidate>
        <mat-form-field appearance="outline" class="full">
          <mat-label>Name</mat-label>
          <input matInput formControlName="name" maxlength="80" cdkFocusInitial />
          <mat-error>Enter a name</mat-error>
        </mat-form-field>
        <mat-form-field appearance="outline" class="full">
          <mat-label>Description (optional)</mat-label>
          <input matInput formControlName="description" maxlength="300" />
        </mat-form-field>
        <fieldset>
          <legend>Shown on these menus</legend>
          @for (m of data.mealTypes; track m.id) {
            <mat-checkbox [checked]="selected().has(m.id)" (change)="toggle(m.id, $event.checked)">{{ m.name }}</mat-checkbox>
          }
        </fieldset>
      </form>
      @if (error()) {
        <p class="err" role="alert">{{ error() }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="undefined">Cancel</button>
      <button mat-flat-button type="submit" form="cat-form" [disabled]="saving()">Save</button>
    </mat-dialog-actions>
  `,
  styles: `
    .full {
      width: 100%;
    }
    fieldset {
      border: 0;
      padding: 0;
      display: grid;
      grid-template-columns: 1fr 1fr;
    }
    legend {
      font-size: 0.85rem;
      color: var(--wl-text-soft);
      margin-bottom: 0.3rem;
    }
    .err {
      color: #a3321c;
    }
  `,
})
export class CategoryDialogComponent {
  protected readonly data = inject<CategoryDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<CategoryDialogComponent, AdminMenu>);
  private readonly menu = inject(MenuService);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly selected = signal(
    new Set(this.data.category?.meal_type_ids ?? (this.data.defaultMealTypeId ? [this.data.defaultMealTypeId] : [])),
  );
  protected readonly form = inject(NonNullableFormBuilder).group({
    name: [this.data.category?.name ?? '', [Validators.required, Validators.maxLength(80)]],
    description: [this.data.category?.description ?? ''],
  });

  protected toggle(id: string, on: boolean): void {
    this.selected.update((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  protected save(): void {
    if (this.form.invalid) return this.form.markAllAsTouched();
    if (!this.selected().size) {
      this.error.set('Choose at least one menu.');
      return;
    }
    const body = { ...this.form.getRawValue(), meal_type_ids: [...this.selected()] };
    this.saving.set(true);
    const req = this.data.category
      ? this.menu.updateCategory(this.data.category.id, body)
      : this.menu.createCategory(body);
    req.subscribe({
      next: (m) => this.ref.close(m),
      error: (e: ApiError) => {
        this.saving.set(false);
        this.error.set(e.message);
      },
    });
  }
}
