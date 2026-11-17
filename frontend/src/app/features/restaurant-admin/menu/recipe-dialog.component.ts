import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { forkJoin } from 'rxjs';

import { ApiError } from '../../../core/http/api-error';
import { InventoryItem, InventoryService, Recipe, Unit, recipeUnits } from '../../../core/inventory/inventory.service';
import { AdminItem } from '../../../core/restaurant/menu.service';
import { formatPrice } from '../../../core/storefront/storefront.models';

interface Line {
  inventory_item_id: string;
  variant_id: string | null;
  quantity: string | number;
  unit: Unit;
}

/** Ingredients of a dish (PRD §8.5). Deducted from stock when the kitchen accepts an order. */
@Component({
  selector: 'wl-recipe-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: '../inventory/inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>{{ dish.name }} — recipe</h2>
    <mat-dialog-content>
      @if (loadError(); as e) {
        <p class="err" role="alert">{{ e }}</p>
      } @else if (!items()) {
        <p class="hint">Loading…</p>
      } @else if (!items()!.length) {
        <p class="hint">Add raw materials under <b>Inventory</b> first, then map them to this dish.</p>
      } @else {
        <form class="form" id="recipe-form" (ngSubmit)="save()">
          <p class="hint">Quantities for <b>one portion</b>. They are taken from stock when the kitchen accepts an order,
            and put back if the order is cancelled.@if (dish.variants.length) { Lines for a size replace the "Every size" lines for that size. }</p>
          <div class="lines">
            @for (l of lines; track $index; let i = $index) {
              <div class="line">
                <label class="field"><span>Ingredient</span>
                  <select [name]="'ing' + i" [(ngModel)]="l.inventory_item_id" (ngModelChange)="pick(l)" data-testid="recipe-item">
                    <option value="">Choose…</option>
                    @for (it of items(); track it.id) { <option [value]="it.id">{{ it.name }}</option> }
                  </select></label>
                <label class="field"><span>Quantity</span>
                  <input [name]="'q' + i" type="number" min="0" step="0.001" [(ngModel)]="l.quantity" data-testid="recipe-qty" /></label>
                <label class="field"><span>Unit</span>
                  <select [name]="'u' + i" [(ngModel)]="l.unit">
                    @for (u of unitsFor(l); track u) { <option [value]="u">{{ u }}</option> }
                  </select></label>
                @if (dish.variants.length) {
                  <label class="field"><span>Size</span>
                    <select [name]="'v' + i" [(ngModel)]="l.variant_id">
                      <option [ngValue]="null">Every size</option>
                      @for (v of dish.variants; track v.id) { <option [ngValue]="v.id">{{ v.name }} only</option> }
                    </select></label>
                }
                <button mat-icon-button type="button" (click)="lines.splice(i, 1)" aria-label="Remove ingredient"><mat-icon>delete</mat-icon></button>
              </div>
            }
          </div>
          <button mat-button type="button" (click)="add()" data-testid="recipe-add"><mat-icon>add</mat-icon>Add ingredient</button>
          @if (cost() !== null) { <p class="hint">Ingredient cost per portion: <b>{{ price(cost()!) }}</b> (dish price {{ price(dish.base_price) }})</p> }
          @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
        </form>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="submit" form="recipe-form" [disabled]="busy() || !valid()" data-testid="save-recipe">Save recipe</button>
    </mat-dialog-actions>
  `,
})
export class RecipeDialogComponent implements OnInit {
  protected readonly dish = inject<AdminItem>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<RecipeDialogComponent, Recipe>);
  private readonly api = inject(InventoryService);
  protected readonly items = signal<InventoryItem[] | null>(null);
  protected readonly cost = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected lines: Line[] = [];

  ngOnInit(): void {
    forkJoin({ items: this.api.items(), recipe: this.api.recipe(this.dish.id) }).subscribe({
      next: ({ items, recipe }) => {
        this.items.set(items.filter((i) => i.is_active || recipe.lines.some((l) => l.inventory_item_id === i.id)));
        this.lines = recipe.lines.map((l) => ({ inventory_item_id: l.inventory_item_id, variant_id: l.variant_id, quantity: +l.quantity, unit: l.unit }));
        if (!this.lines.length) this.add();
        this.cost.set(recipe.lines.length ? recipe.cost : null);
      },
      error: (e: ApiError) =>
        this.loadError.set(e.status === 402 ? 'Recipes are part of the Professional plan.' : e.message),
    });
  }

  protected add(): void {
    this.lines.push({ inventory_item_id: '', variant_id: null, quantity: '', unit: 'g' });
  }

  protected unitsFor(l: Line): Unit[] {
    const it = this.items()?.find((i) => i.id === l.inventory_item_id);
    return it ? recipeUnits(it.unit) : ['g'];
  }

  protected pick(l: Line): void {
    const allowed = this.unitsFor(l);
    if (!allowed.includes(l.unit)) l.unit = allowed[0];
  }

  protected price(v: string | number): string {
    return formatPrice(v);
  }

  protected valid(): boolean {
    const keys = this.lines.map((l) => `${l.variant_id}|${l.inventory_item_id}`);
    return new Set(keys).size === keys.length && this.lines.every((l) => l.inventory_item_id && +l.quantity > 0);
  }

  protected save(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api
      .saveRecipe(
        this.dish.id,
        this.lines.map((l) => ({ ...l, quantity: String(l.quantity) })),
      )
      .subscribe({
        next: (r) => this.ref.close(r),
        error: (e: ApiError) => {
          this.busy.set(false);
          this.error.set(e.message);
        },
      });
  }
}
