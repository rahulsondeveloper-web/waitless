import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnInit,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';

import { CartLine } from '../../../core/ordering/cart.service';
import { MenuAddonGroup, PublicItem, formatPrice } from '../../../core/storefront/storefront.models';

/** Choose size, extras, quantity and instructions for one dish, then add it to the cart. */
@Component({
  selector: 'wl-dish-picker',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'closed.emit()' },
  template: `
    <div class="backdrop" (click)="closed.emit()"></div>
    <div class="sheet" role="dialog" aria-modal="true" [attr.aria-label]="item().name" tabindex="-1">
      <header>
        <h2>{{ item().name }}</h2>
        <button type="button" class="x" (click)="closed.emit()" aria-label="Close">
          <span class="material-symbols-outlined" aria-hidden="true">close</span>
        </button>
      </header>
      @if (item().description) { <p class="desc">{{ item().description }}</p> }

      @if (item().variants.length) {
        <fieldset>
          <legend>Size <small>required</small></legend>
          @for (v of item().variants; track v.id) {
            <label class="opt">
              <input type="radio" name="variant" [checked]="variantId() === v.id" (change)="variantId.set(v.id)" />
              <span>{{ v.name }}</span><b>{{ price(v.price) }}</b>
            </label>
          }
        </fieldset>
      }

      @for (g of item().addon_groups; track g.id) {
        <fieldset>
          <legend>{{ g.name }} <small>{{ rule(g) }}</small></legend>
          @for (a of g.addons; track a.id) {
            <label class="opt">
              <input [type]="g.max_select === 1 && g.min_select === 1 ? 'radio' : 'checkbox'" [name]="g.id"
                     [checked]="picked().has(a.id)" [disabled]="!picked().has(a.id) && full(g) && g.max_select > 1"
                     (change)="toggle(g, a.id)" />
              <span>{{ a.name }}</span><b>{{ +a.price ? '+ ' + price(a.price) : 'Free' }}</b>
            </label>
          }
        </fieldset>
      }

      <label class="field">
        <span>Instructions (optional)</span>
        <input type="text" maxlength="200" [value]="instructions()" (input)="instructions.set($any($event.target).value)"
               placeholder="Less spicy, no onion…" />
      </label>

      <footer>
        <div class="qty" role="group" aria-label="Quantity">
          <button type="button" (click)="qty.set(Math.max(1, qty() - 1))" aria-label="One less">−</button>
          <span aria-live="polite">{{ qty() }}</span>
          <button type="button" (click)="qty.set(Math.min(50, qty() + 1))" aria-label="One more">+</button>
        </div>
        @if (problem(); as p) { <span class="need">{{ p }}</span> }
        <button type="button" class="wl-btn wl-btn--primary" [disabled]="!!problem()" (click)="add()" data-testid="add-to-cart">
          Add · {{ price(lineTotal()) }}
        </button>
      </footer>
    </div>
  `,
  styles: `
    :host {
      position: fixed;
      inset: 0;
      z-index: 1000;
      display: grid;
      place-items: end center;
      @media (min-width: 640px) {
        place-items: center;
      }
    }
    .backdrop {
      position: absolute;
      inset: 0;
      background: rgba(20, 12, 8, 0.45);
    }
    .sheet {
      position: relative;
      width: min(520px, 100%);
      max-height: 90vh;
      overflow: auto;
      background: var(--wl-surface);
      border-radius: 20px 20px 0 0;
      padding: 1.2rem 1.2rem 0;
      display: grid;
      gap: 0.9rem;
      @media (min-width: 640px) {
        border-radius: 20px;
      }
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 1rem;
      h2 {
        font: 600 1.5rem var(--wl-font-serif);
      }
    }
    .x {
      border: 0;
      background: none;
      cursor: pointer;
      color: var(--wl-muted);
    }
    .desc {
      color: var(--wl-text-soft);
      font-size: 0.9rem;
    }
    fieldset {
      border: 0;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 0.35rem;
    }
    legend {
      font-weight: 600;
      margin-bottom: 0.3rem;
      small {
        font-weight: 400;
        color: var(--wl-muted);
        margin-left: 0.3rem;
      }
    }
    .opt {
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 0.6rem;
      align-items: center;
      padding: 0.55rem 0.7rem;
      border: 1px solid var(--wl-line);
      border-radius: 10px;
      cursor: pointer;
      min-height: 44px;
      b {
        font-weight: 600;
        font-size: 0.9rem;
      }
    }
    .field {
      display: grid;
      gap: 0.3rem;
      font-size: 0.9rem;
      input {
        font: inherit;
        padding: 0.65rem 0.8rem;
        border: 1.5px solid var(--wl-line);
        border-radius: 10px;
      }
    }
    footer {
      position: sticky;
      bottom: 0;
      background: var(--wl-surface);
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      align-items: center;
      justify-content: space-between;
      padding: 0.8rem 0 1rem;
      border-top: 1px solid var(--wl-line);
    }
    .qty {
      display: inline-flex;
      align-items: center;
      gap: 0.6rem;
      button {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        border: 1.5px solid var(--wl-line);
        background: #fff;
        font-size: 1.2rem;
        cursor: pointer;
      }
      span {
        min-width: 1.5rem;
        text-align: center;
        font-weight: 600;
      }
    }
    .need {
      font-size: 0.8rem;
      color: #8a2a17;
    }
    .wl-btn:disabled {
      opacity: 0.55;
    }
  `,
})
export class DishPickerComponent implements OnInit {
  readonly item = input.required<PublicItem>();
  readonly currency = input('INR');
  readonly basePrice = input.required<number>(); // branch price (no variants)
  readonly added = output<Omit<CartLine, 'key'>>();
  readonly closed = output<void>();
  protected readonly Math = Math;
  private readonly el = inject(ElementRef<HTMLElement>);

  protected readonly variantId = signal<string | null>(null);
  protected readonly picked = signal<Set<string>>(new Set());
  protected readonly qty = signal(1);
  protected readonly instructions = signal('');

  protected readonly unit = computed(() => {
    const it = this.item();
    const v = it.variants.find((x) => x.id === this.variantId());
    const base = it.variants.length ? (v ? +v.price : 0) : this.basePrice();
    const extras = it.addon_groups.flatMap((g) => g.addons).filter((a) => this.picked().has(a.id));
    return base + extras.reduce((s, a) => s + +a.price, 0);
  });
  protected readonly lineTotal = computed(() => this.unit() * this.qty());
  protected readonly problem = computed(() => {
    const it = this.item();
    if (it.variants.length && !this.variantId()) return 'Choose a size';
    for (const g of it.addon_groups) {
      const n = g.addons.filter((a) => this.picked().has(a.id)).length;
      if (n < g.min_select) return `Choose ${g.min_select === g.max_select ? g.min_select : 'at least ' + g.min_select} from ${g.name}`;
    }
    return null;
  });

  ngOnInit(): void {
    const it = this.item();
    if (it.variants.length === 1) this.variantId.set(it.variants[0].id);
    queueMicrotask(() => (this.el.nativeElement.querySelector('.sheet') as HTMLElement | null)?.focus());
  }

  protected price(v: string | number): string {
    return formatPrice(v, this.currency());
  }

  protected rule(g: MenuAddonGroup): string {
    if (g.min_select === 0) return g.max_select === 1 ? 'optional, pick 1' : `optional, up to ${g.max_select}`;
    return g.min_select === g.max_select ? `pick ${g.min_select}` : `pick ${g.min_select}–${g.max_select}`;
  }

  protected full(g: MenuAddonGroup): boolean {
    return g.addons.filter((a) => this.picked().has(a.id)).length >= g.max_select;
  }

  protected toggle(g: MenuAddonGroup, id: string): void {
    const next = new Set(this.picked());
    if (g.max_select === 1) {
      const wasOn = next.has(id);
      g.addons.forEach((a) => next.delete(a.id));
      if (!wasOn || g.min_select === 1) next.add(id);
    } else if (next.has(id)) next.delete(id);
    else if (!this.full(g)) next.add(id);
    this.picked.set(next);
  }

  protected add(): void {
    const it = this.item();
    const addons = it.addon_groups.flatMap((g) => g.addons).filter((a) => this.picked().has(a.id));
    this.added.emit({
      menu_item_id: it.id,
      name: it.name,
      food_class: it.food_class,
      variant_id: this.variantId(),
      variant_name: it.variants.find((v) => v.id === this.variantId())?.name ?? null,
      addon_ids: addons.map((a) => a.id),
      addon_names: addons.map((a) => a.name),
      unit_price: this.unit(),
      tax_pct: +it.tax_pct,
      quantity: this.qty(),
      instructions: this.instructions().trim(),
    });
  }
}
