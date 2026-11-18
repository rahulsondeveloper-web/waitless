import { NgTemplateOutlet, ViewportScroller } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';

import { ActivatedRoute, RouterLink } from '@angular/router';

import { ApiError } from '../../../core/http/api-error';
import { CartLine, CartService } from '../../../core/ordering/cart.service';
import { OrderingService, itemPrice, unavailableReason } from '../../../core/ordering/ordering.service';
import { PublicCategory, PublicItem, PublicMenu, formatPrice, categoryImage } from '../../../core/storefront/storefront.models';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { DishPickerComponent } from './dish-picker.component';

const FOOD_LABEL = { veg: 'Vegetarian', non_veg: 'Non-vegetarian', egg: 'Contains egg' } as const;

/** Footer lines of each spread, as in the Remelle template. */
const QUOTES = [
  'Life is soup-erb with you around.',
  "It's impastable not to love this!",
  'Stressed spelled backward is desserts.',
  'Good food, good mood.',
  'Eat well, laugh often, love abundantly.',
  'Made with love, served with joy.',
];

/** Items under one subcategory heading (name null = no subcategory). */
export interface ItemGroup {
  name: string | null;
  items: PublicItem[];
}

/**
 * One magazine "spread" of the template: two pages, usually two categories. The three page designs
 * of the template take turns: (a) photo page + list, (b) photo panel + accent list, (c) big title with a
 * round plate photo + labelled list with a framed photo. A lone last category uses (a).
 */
export interface Spread {
  id: string;
  layout: 'a' | 'b' | 'c';
  first: PublicCategory;
  second: PublicCategory | null;
  quote: string;
}

const hasTag = (i: PublicItem, tag: string) => i.tags.some((t) => t.trim().toLowerCase() === tag);

/** Restaurant menu (PRD §6 Menu, §7.3) with ordering (PRD §13): pick options → cart. */
@Component({
  selector: 'wl-storefront-menu',
  imports: [NgTemplateOutlet, LoadingStateComponent, ErrorStateComponent, EmptyStateComponent, DishPickerComponent, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './menu.page.html',
  styleUrl: './menu.page.scss',
})
export class StorefrontMenuPage implements OnInit {
  protected readonly ctx = inject(TenantContextService);
  private readonly scroller = inject(ViewportScroller);
  private readonly route = inject(ActivatedRoute);
  private readonly ordering = inject(OrderingService);
  protected readonly cart = inject(CartService);
  protected readonly picking = signal<PublicItem | null>(null);
  protected readonly toast = signal<string | null>(null);
  /** Branch whose prices/availability apply: the guest's table, else the main branch. */
  protected readonly branchId = signal<string | null>(null);
  protected readonly canOrder = computed(() => !!this.menu()?.ordering_enabled && !this.ctx.preview());
  private readonly tz = computed(
    () => this.ctx.restaurant()?.branches.find((b) => b.id === this.branchId())?.timezone ?? 'Asia/Kolkata',
  );

  protected readonly menu = signal<PublicMenu | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly meal = signal<string | null>(null); // null = all
  protected readonly query = signal('');
  protected readonly vegOnly = signal(false);
  protected readonly foodLabel = FOOD_LABEL;

  protected readonly categories = computed<PublicCategory[]>(() => {
    const m = this.menu();
    if (!m) return [];
    const meal = this.meal();
    const q = this.query().trim().toLowerCase();
    return m.categories
      .filter((c) => !meal || c.meal_type_ids.includes(meal))
      .map((c) => ({
        ...c,
        items: c.items.filter(
          (i) =>
            (!this.vegOnly() || i.food_class === 'veg') &&
            (!q || i.name.toLowerCase().includes(q) || i.description.toLowerCase().includes(q)),
        ),
      }))
      .filter((c) => c.items.length);
  });

  protected readonly spreads = computed<Spread[]>(() => {
    const cats = this.categories();
    const out: Spread[] = [];
    for (let i = 0; i < cats.length; i += 2) {
      const n = out.length;
      const second = cats[i + 1] ?? null;
      out.push({
        id: cats[i].id,
        layout: second ? (['a', 'b', 'c'] as const)[n % 3] : 'a',
        first: cats[i],
        second,
        quote: QUOTES[n % QUOTES.length],
      });
    }
    return out;
  });

  /** Legend entries, only for marks this menu actually uses. */
  protected readonly legend = computed(() => {
    const items = (this.menu()?.categories ?? []).flatMap((c) => c.items);
    return {
      bestseller: items.some((i) => i.is_bestseller),
      special: items.some((i) => i.is_todays_special),
      classic: items.some((i) => hasTag(i, 'classic')),
      jain: items.some((i) => hasTag(i, 'jain')),
      custom: items.some((i) => this.customisable(i)),
    };
  });

  ngOnInit(): void {
    this.load();
    this.branchId.set(this.ctx.primaryBranch()?.id ?? null);
    const pre = this.route.snapshot.queryParamMap.get('preorder');
    if (pre) {
      this.cart.setTableToken(null);
      this.cart.setPreorder(pre);
    }
    const token = this.cart.tableToken();
    if (token) {
      this.ordering.tableView(token).subscribe({
        next: (t) => this.branchId.set(t.branch_id),
        error: () => this.cart.setTableToken(null), // expired or a new PIN was issued
      });
    }
  }

  protected unavailable(i: PublicItem): string | null {
    return unavailableReason(i, this.branchId(), this.tz());
  }

  protected shownPrice(i: PublicItem): string {
    const p = this.price(itemPrice(i, this.branchId()));
    return i.variants.length > 1 ? `from ${p}` : p;
  }

  protected basePrice(i: PublicItem): number {
    return itemPrice(i, this.branchId());
  }

  protected added(line: Omit<CartLine, 'key'>): void {
    this.cart.add(line);
    this.picking.set(null);
    this.toast.set(`${line.quantity} × ${line.name} added`);
    setTimeout(() => this.toast.set(null), 2500);
  }

  protected load(): void {
    this.error.set(null);
    this.ctx.menu().subscribe({ next: (m) => this.menu.set(m), error: (e: ApiError) => this.error.set(e) });
  }

  protected price(v: string | number): string {
    return formatPrice(v, this.menu()?.currency ?? 'INR');
  }

  protected catImage(c: { name: string; image_url?: string | null }): string {
    return categoryImage(c.name, c.image_url);
  }

  protected jump(id: string): void {
    this.scroller.setOffset([0, 140]);
    this.scroller.scrollToAnchor(`cat-${id}`);
  }

  // ---------- template helpers ----------

  /** Subcategory groups in menu order (template "napoletana style" / "sourdough style" headings). */
  protected groups(items: PublicItem[]): ItemGroup[] {
    const out: ItemGroup[] = [];
    for (const i of items) {
      const name = i.subcategory || null;
      const g = out.find((x) => x.name === name);
      if (g) g.items.push(i);
      else out.push({ name, items: [i] });
    }
    return out;
  }

  /** "Soup Bowls" → head "Soup", tail "Bowls" (the template sets the tail in script / small caps). */
  protected head(name: string): string {
    const i = name.indexOf(' ');
    return i > 0 ? name.slice(0, i) : name;
  }
  protected tail(name: string): string {
    const i = name.indexOf(' ');
    return i > 0 ? name.slice(i + 1) : '';
  }

  /** Right page of design (c): main list, then a framed photo beside the rest ("Signature cocktails"). */
  protected drinkSplit(c: PublicCategory): { mainTitle: string | null; main: PublicItem[]; featureTitle: string | null; feature: PublicItem[] } {
    const g = this.groups(c.items);
    if (g.length > 1) {
      return { mainTitle: g[0].name, main: g[0].items, featureTitle: g[1].name, feature: g.slice(1).flatMap((x) => x.items) };
    }
    const n = c.items.length;
    const cut = n > 4 ? n - 3 : 0;
    return { mainTitle: g[0]?.name ?? null, main: c.items.slice(0, cut), featureTitle: null, feature: c.items.slice(cut) };
  }

  protected highlight(c: PublicCategory): string | null {
    return (c.items.find((i) => i.is_bestseller || i.is_todays_special) ?? c.items[0])?.name ?? null;
  }

  protected food(i: PublicItem): string {
    return FOOD_LABEL[i.food_class];
  }

  protected customisable(i: PublicItem): boolean {
    return i.variants.length > 1 || i.addon_groups.length > 0;
  }
  protected classic(i: PublicItem): boolean {
    return hasTag(i, 'classic');
  }
  protected jain(i: PublicItem): boolean {
    return hasTag(i, 'jain');
  }

  /** Price split as the template shows it: muted currency sign, then the amount. */
  protected priceParts(i: PublicItem): { from: boolean; sign: string; amount: string } {
    const full = this.price(itemPrice(i, this.branchId()));
    const m = /^([^\d]*)(.*)$/.exec(full);
    return { from: i.variants.length > 1, sign: (m?.[1] ?? '').trim(), amount: m?.[2] ?? full };
  }

  protected spice(level: number): string {
    return '🌶'.repeat(level);
  }
}
