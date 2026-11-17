import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';

import { ApiError } from '../../../core/http/api-error';
import {
  Order,
  OrderLineIn,
  OrderingService,
  itemPrice,
  newIdempotencyKey,
  unavailableReason,
} from '../../../core/ordering/ordering.service';
import { BoardTable } from '../../../core/restaurant/operations.service';
import { StorefrontApi } from '../../../core/storefront/storefront.api';
import { PublicItem, formatPrice } from '../../../core/storefront/storefront.models';

export interface NewOrderData {
  branchId: string;
  timezone: string;
  tables: BoardTable[]; // occupied tables (with an open session)
  tableId?: string;
}

interface Line extends OrderLineIn {
  label: string;
  unit: number;
}

/** Waiter takes an order for a table (PRD §13): pick table → dishes (size, extras, qty, note) → send. */
@Component({
  selector: 'wl-new-order-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>New order</h2>
    <mat-dialog-content class="content">
      <label class="field">
        <span>Table</span>
        <select [(ngModel)]="sessionId" name="table" data-testid="order-table">
          <option value="">Choose a seated table…</option>
          @for (t of data.tables; track t.id) {
            <option [value]="t.session!.id">{{ t.label }} · {{ t.session!.public_code }}{{ t.session!.guest_name ? ' · ' + t.session!.guest_name : '' }}</option>
          }
        </select>
      </label>

      <div class="pick">
        <label class="field grow">
          <span>Dish</span>
          <input list="dishes" [(ngModel)]="query" name="q" placeholder="Search the menu" (change)="choose()" data-testid="order-dish" />
          <datalist id="dishes">
            @for (i of orderable(); track i.id) { <option [value]="i.name"></option> }
          </datalist>
        </label>
      </div>

      @if (item(); as it) {
        <div class="opts">
          @if (it.variants.length) {
            <label class="field"><span>Size</span>
              <select [(ngModel)]="variantId" name="variant">
                @for (v of it.variants; track v.id) { <option [value]="v.id">{{ v.name }} · {{ price(v.price) }}</option> }
              </select></label>
          }
          @for (g of it.addon_groups; track g.id) {
            <fieldset>
              <legend>{{ g.name }} ({{ g.min_select }}–{{ g.max_select }})</legend>
              @for (a of g.addons; track a.id) {
                <label class="chk"><input type="checkbox" [checked]="addons().has(a.id)" (change)="toggle(a.id)" />
                  {{ a.name }} {{ +a.price ? '+' + price(a.price) : '' }}</label>
              }
            </fieldset>
          }
          <label class="field"><span>Qty</span><input type="number" min="1" max="50" [(ngModel)]="qty" name="qty" class="narrow" /></label>
          <label class="field grow"><span>Note</span><input [(ngModel)]="note" name="note" maxlength="200" /></label>
          <button mat-stroked-button type="button" (click)="addLine()" data-testid="order-add-line"><mat-icon>add</mat-icon>Add</button>
        </div>
      }

      @if (lines().length) {
        <ul class="lines">
          @for (l of lines(); track $index) {
            <li><span>{{ l.quantity }} × {{ l.label }}</span><span>{{ price(l.unit * l.quantity) }}</span>
              <button mat-icon-button type="button" (click)="remove($index)" aria-label="Remove"><mat-icon>close</mat-icon></button></li>
          }
          <li class="sum"><span>Food (before tax)</span><span>{{ price(subtotal()) }}</span><span></span></li>
        </ul>
      }
      @if (error(); as e) { <p class="err" role="alert">{{ e }}</p> }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="undefined">Cancel</button>
      <button mat-flat-button type="button" [disabled]="busy() || !sessionId || !lines().length" (click)="send()" data-testid="order-send">
        Send to kitchen
      </button>
    </mat-dialog-actions>
  `,
  styles: `
    .content {
      display: grid;
      gap: 0.8rem;
      min-width: min(560px, 82vw);
    }
    .field {
      display: grid;
      gap: 0.2rem;
      font-size: 0.8rem;
      color: var(--wl-muted);
      select,
      input {
        font: inherit;
        font-size: 0.95rem;
        padding: 0.45rem 0.6rem;
        border: 1px solid var(--wl-line);
        border-radius: 8px;
        color: var(--wl-text);
      }
    }
    .grow {
      flex: 1 1 200px;
    }
    .narrow {
      width: 4.5rem;
    }
    .opts {
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      align-items: flex-end;
      padding: 0.6rem;
      border-radius: 10px;
      background: var(--wl-surface-alt);
    }
    fieldset {
      border: 0;
      margin: 0;
      padding: 0;
      display: grid;
      legend {
        font-size: 0.8rem;
        color: var(--wl-muted);
      }
    }
    .chk {
      font-size: 0.9rem;
    }
    .lines {
      list-style: none;
      margin: 0;
      padding: 0;
      li {
        display: grid;
        grid-template-columns: 1fr auto 40px;
        align-items: center;
        gap: 0.4rem;
      }
      .sum {
        font-weight: 600;
        border-top: 1px dashed var(--wl-line);
        padding-top: 0.3rem;
      }
    }
    .err {
      color: #a3321c;
    }
  `,
})
export class NewOrderDialogComponent implements OnInit {
  protected readonly data = inject<NewOrderData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<NewOrderDialogComponent, Order>);
  private readonly menuApi = inject(StorefrontApi);
  private readonly api = inject(OrderingService);

  protected readonly items = signal<PublicItem[]>([]);
  protected readonly item = signal<PublicItem | null>(null);
  protected readonly addons = signal<Set<string>>(new Set());
  protected readonly lines = signal<Line[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected sessionId = '';
  protected query = '';
  protected variantId = '';
  protected qty = 1;
  protected note = '';
  private key = newIdempotencyKey();

  protected readonly orderable = computed(() =>
    this.items().filter((i) => !unavailableReason(i, this.data.branchId, this.data.timezone)),
  );
  protected readonly subtotal = computed(() => this.lines().reduce((s, l) => s + l.unit * l.quantity, 0));

  ngOnInit(): void {
    const t = this.data.tables.find((x) => x.id === this.data.tableId);
    if (t?.session) this.sessionId = t.session.id;
    this.menuApi.previewMenu().subscribe((m) => this.items.set(m.categories.flatMap((c) => c.items)));
  }

  protected price(v: string | number): string {
    return formatPrice(v);
  }

  protected choose(): void {
    const it = this.orderable().find((i) => i.name.toLowerCase() === this.query.trim().toLowerCase()) ?? null;
    this.item.set(it);
    this.addons.set(new Set());
    this.variantId = it?.variants[0]?.id ?? '';
    this.qty = 1;
    this.note = '';
  }

  protected toggle(id: string): void {
    const next = new Set(this.addons());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.addons.set(next);
  }

  protected addLine(): void {
    const it = this.item();
    if (!it) return;
    const v = it.variants.find((x) => x.id === this.variantId);
    const extras = it.addon_groups.flatMap((g) => g.addons).filter((a) => this.addons().has(a.id));
    const unit = (v ? +v.price : itemPrice(it, this.data.branchId)) + extras.reduce((s, a) => s + +a.price, 0);
    const label = [it.name + (v ? ` (${v.name})` : ''), ...extras.map((a) => `+${a.name}`)].join(' ') + (this.note ? ` — “${this.note}”` : '');
    this.lines.set([
      ...this.lines(),
      {
        menu_item_id: it.id,
        variant_id: v?.id ?? null,
        addon_ids: extras.map((a) => a.id),
        quantity: Math.max(1, Math.min(50, Math.floor(this.qty || 1))),
        instructions: this.note.trim(),
        label,
        unit,
      },
    ]);
    this.item.set(null);
    this.query = '';
    this.key = newIdempotencyKey();
  }

  protected remove(i: number): void {
    this.lines.set(this.lines().filter((_, n) => n !== i));
    this.key = newIdempotencyKey();
  }

  protected send(): void {
    this.busy.set(true);
    this.error.set(null);
    const items = this.lines().map(({ label: _l, unit: _u, ...rest }) => rest);
    this.api.staffOrder(this.sessionId, items, '', this.key).subscribe({
      next: (o) => this.ref.close(o),
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }
}
