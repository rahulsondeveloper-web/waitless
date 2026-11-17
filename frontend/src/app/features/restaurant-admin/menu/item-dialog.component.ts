import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatChipsModule } from '@angular/material/chips';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { startWith } from 'rxjs';

import { ApiError } from '../../../core/http/api-error';
import { ALLERGENS, AdminCategory, AdminItem, ItemInput, MenuService } from '../../../core/restaurant/menu.service';
import { FoodClass } from '../../../core/storefront/storefront.models';

export interface ItemDialogData {
  item: AdminItem | null; // null = new
  categories: AdminCategory[];
  categoryId: string;
}

/** Create / edit a dish (PRD §7.3 fields available in Phase 4). Closes with the saved item. */
@Component({
  selector: 'wl-item-dialog',
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatChipsModule,
    MatButtonModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>{{ data.item ? 'Edit dish' : 'Add a dish' }}</h2>
    <mat-dialog-content>
      <form [formGroup]="form" id="item-form" (ngSubmit)="save()" class="grid" novalidate>
        <mat-form-field appearance="outline" class="span-2">
          <mat-label>Name</mat-label>
          <input matInput formControlName="name" maxlength="120" cdkFocusInitial />
          <mat-error>Enter a name</mat-error>
        </mat-form-field>
        <mat-form-field appearance="outline" class="span-2">
          <mat-label>Description</mat-label>
          <textarea matInput formControlName="description" rows="2" maxlength="1000"></textarea>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Price (₹)</mat-label>
          <input matInput type="number" min="0" step="0.5" formControlName="base_price" inputmode="decimal" />
          <mat-error>Enter a price of 0 or more</mat-error>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Preparation time (min)</mat-label>
          <input matInput type="number" min="0" max="240" formControlName="prep_minutes" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Category</mat-label>
          <mat-select formControlName="category_id">
            @for (c of data.categories; track c.id) {
              <mat-option [value]="c.id">{{ c.name }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Subcategory</mat-label>
          <mat-select formControlName="subcategory_id">
            <mat-option [value]="null">None</mat-option>
            @for (s of subcategories(); track s.id) {
              <mat-option [value]="s.id">{{ s.name }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Food type</mat-label>
          <mat-select formControlName="food_class">
            <mat-option value="veg">Vegetarian</mat-option>
            <mat-option value="egg">Contains egg</mat-option>
            <mat-option value="non_veg">Non-vegetarian</mat-option>
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Spice level</mat-label>
          <mat-select formControlName="spice_level">
            <mat-option [value]="0">Not spicy</mat-option>
            <mat-option [value]="1">Mild</mat-option>
            <mat-option [value]="2">Medium</mat-option>
            <mat-option [value]="3">Hot</mat-option>
          </mat-select>
        </mat-form-field>
        <div class="span-2">
          <p class="label" id="allergen-label">Allergens</p>
          <mat-chip-listbox formControlName="allergens" multiple aria-labelledby="allergen-label">
            @for (a of allergens; track a) {
              <mat-chip-option [value]="a">{{ a }}</mat-chip-option>
            }
          </mat-chip-listbox>
        </div>
        <mat-checkbox formControlName="is_bestseller">Bestseller</mat-checkbox>
        <mat-checkbox formControlName="is_todays_special">Today's special</mat-checkbox>
      </form>
      @if (error()) {
        <p class="err" role="alert">{{ error() }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="undefined">Cancel</button>
      <button mat-flat-button type="submit" form="item-form" [disabled]="saving()">
        {{ data.item ? 'Save changes' : 'Add dish' }}
      </button>
    </mat-dialog-actions>
  `,
  styles: `
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      column-gap: 1rem;
      padding-top: 0.4rem;
    }
    .span-2 {
      grid-column: 1 / -1;
    }
    .label {
      font-size: 0.85rem;
      color: var(--wl-text-soft);
      margin-bottom: 0.3rem;
    }
    mat-chip-listbox {
      display: block;
      margin-bottom: 0.8rem;
    }
    .err {
      color: #a3321c;
    }
    @media (max-width: 600px) {
      .grid {
        grid-template-columns: 1fr;
      }
    }
  `,
})
export class ItemDialogComponent {
  protected readonly data = inject<ItemDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<ItemDialogComponent, AdminItem>);
  private readonly menu = inject(MenuService);
  protected readonly allergens = ALLERGENS;
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly form = inject(NonNullableFormBuilder).group({
    name: [this.data.item?.name ?? '', [Validators.required, Validators.maxLength(120)]],
    description: [this.data.item?.description ?? ''],
    base_price: [this.data.item ? Number(this.data.item.base_price) : (null as number | null), [Validators.required, Validators.min(0)]],
    prep_minutes: [this.data.item?.prep_minutes ?? 15, [Validators.min(0), Validators.max(240)]],
    category_id: [this.data.item?.category_id ?? this.data.categoryId, Validators.required],
    subcategory_id: [this.data.item?.subcategory_id ?? (null as string | null)],
    food_class: [(this.data.item?.food_class ?? 'veg') as FoodClass],
    spice_level: [this.data.item?.spice_level ?? 0],
    allergens: [this.data.item?.allergens ?? ([] as string[])],
    is_bestseller: [this.data.item?.is_bestseller ?? false],
    is_todays_special: [this.data.item?.is_todays_special ?? false],
  });

  private readonly categoryId = toSignal(
    this.form.controls.category_id.valueChanges.pipe(startWith(this.form.controls.category_id.value)),
  );
  protected readonly subcategories = computed(
    () => this.data.categories.find((c) => c.id === this.categoryId())?.subcategories ?? [],
  );

  constructor() {
    // Moving to another category clears a subcategory that belongs to the old one.
    this.form.controls.category_id.valueChanges.subscribe(() => this.form.controls.subcategory_id.setValue(null));
  }

  protected save(): void {
    if (this.form.invalid) return this.form.markAllAsTouched();
    const v = this.form.getRawValue();
    const body: ItemInput = { ...v, name: v.name.trim(), base_price: String(v.base_price ?? 0) };
    this.saving.set(true);
    const req = this.data.item ? this.menu.updateItem(this.data.item.id, body) : this.menu.createItem(body);
    req.subscribe({
      next: (item) => this.ref.close(item),
      error: (e: ApiError) => {
        this.saving.set(false);
        this.error.set(e.message);
      },
    });
  }
}
