import { NgTemplateOutlet, ViewportScroller } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';

import { ActivatedRoute, RouterLink } from '@angular/router';

import { ApiError } from '../../../core/http/api-error';
import { CartLine, CartService } from '../../../core/ordering/cart.service';
import { OrderingService, itemPrice, unavailableReason } from '../../../core/ordering/ordering.service';
import {
  MenuQuery,
  PublicCategory,
  PublicItem,
  PublicMenu,
  categoryImage,
  formatPrice,
} from '../../../core/storefront/storefront.models';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { NearEndDirective } from '../../../shared/ui/near-end/near-end.directive';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { DishPickerComponent } from './dish-picker.component';

const FOOD_LABEL = { veg: 'Vegetarian', non_veg: 'Non-vegetarian', egg: 'Contains egg' } as const;

/** Dishes per category in the first load and in every "load more" batch. */
export const MENU_BATCH = 10;
/** The next batch is fetched when this many dishes from the end of the loaded ones come into view (8th of 10). */
export const LOAD_AHEAD = 3;

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
  imports: [
    NgTemplateOutlet,
    NearEndDirective,
    LoadingStateComponent,
    ErrorStateComponent,
    EmptyStateComponent,
    DishPickerComponent,
    RouterLink,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './menu.page.html',
  styleUrl: './menu.page.scss',
})
export class StorefrontMenuPage implements OnInit {
  protected readonly ctx = inject(TenantContextService);
  private readonly scroller = inject(ViewportScroller);
  private readonly route = inject(ActivatedRoute);
  private readonly ordering = inject(OrderingService);
  private readonly destroyRef = inject(DestroyRef);
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
  /** Categories whose next batch is on its way / failed to load. */
  protected readonly loadingMore = signal<ReadonlySet<string>>(new Set());
  protected readonly failedMore = signal<ReadonlySet<string>>(new Set());
  /** True while the filters changed and the new results are on their way. */
  protected readonly refreshing = signal(false);
  protected readonly filtersOn = computed(() => this.vegOnly() || !!this.query().trim());
  private generation = 0; // a batch for old filters is ignored
  private searchTimer: ReturnType<typeof setTimeout> | undefined;

  /** Veg-only and search run on the server, so they also cover dishes not loaded yet; meal type is local. */
  protected readonly categories = computed<PublicCategory[]>(() => {
    const m = this.menu();
    if (!m) return [];
    const meal = this.meal();
    return m.categories.filter((c) => (!meal || c.meal_type_ids.includes(meal)) && c.items.length);
  });

  /** Row that fetches the next batch when it scrolls into view: item ID → category ID. */
  protected readonly triggers = computed(() => {
    const map = new Map<string, string>();
    for (const c of this.categories()) {
      const total = c.item_count ?? c.items.length;
      if (c.items.length < total && !this.failedMore().has(c.id)) {
        map.set(c.items[Math.max(0, c.items.length - LOAD_AHEAD)].id, c.id);
      }
    }
    return map;
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

  /** Legend entries, only for marks this menu actually uses (the server knows them for unloaded dishes). */
  protected readonly legend = computed(() => {
    const marks = this.menu()?.marks;
    if (marks) {
      const on = new Set(marks);
      return { bestseller: on.has('bestseller'), special: on.has('special'), classic: on.has('classic'), jain: on.has('jain'), custom: on.has('custom') };
    }
    const items = (this.menu()?.categories ?? []).flatMap((c) => c.items);
    return {
      bestseller: items.some((i) => i.is_bestseller),
      special: items.some((i) => i.is_todays_special),
      classic: items.some((i) => hasTag(i, 'classic')),
      jain: items.some((i) => hasTag(i, 'jain')),
      custom: items.some((i) => this.customisable(i)),
    };
  });

  constructor() {
    // The restaurant edited its menu (server push): fetch again, keeping as many dishes as are shown,
    // so the guest's scroll position and the loaded batches stay.
    let seen = this.ctx.version();
    effect(() => {
      const v = this.ctx.version();
      if (v === seen) return;
      seen = v;
      untracked(() => this.load(true));
    });
  }

  ngOnInit(): void {
    this.load();
    this.destroyRef.onDestroy(() => clearTimeout(this.searchTimer));
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

  private menuQuery(limit = MENU_BATCH): MenuQuery {
    return { limit, veg: this.vegOnly(), q: this.query() };
  }

  /** First batch of every category (with the current filters); `keep` = as many dishes as now shown. */
  protected load(keep = false): void {
    const shown = keep ? Math.max(0, ...(this.menu()?.categories ?? []).map((c) => c.items.length)) : 0;
    const limit = Math.min(100, Math.max(MENU_BATCH, Math.ceil(shown / MENU_BATCH) * MENU_BATCH));
    const gen = ++this.generation;
    this.error.set(null);
    this.refreshing.set(!!this.menu());
    this.loadingMore.set(new Set());
    this.failedMore.set(new Set());
    this.ctx.menuPage(this.menuQuery(limit)).subscribe({
      next: (m) => {
        if (gen !== this.generation) return;
        this.refreshing.set(false);
        this.menu.set(m);
      },
      error: (e: ApiError) => {
        if (gen !== this.generation) return;
        this.refreshing.set(false);
        this.error.set(e);
      },
    });
  }

  protected setVeg(on: boolean): void {
    this.vegOnly.set(on);
    this.load();
  }

  /** Search runs on the server: wait until the guest pauses typing. */
  protected setQuery(q: string): void {
    this.query.set(q);
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.load(), 300);
  }

  /** The next batch of one category, appended to what is shown. */
  protected loadMore(categoryId: string): void {
    const cat = this.menu()?.categories.find((c) => c.id === categoryId);
    if (!cat || this.loadingMore().has(categoryId)) return;
    if (cat.items.length >= (cat.item_count ?? cat.items.length)) return;
    const gen = this.generation;
    this.loadingMore.update((s) => new Set(s).add(categoryId));
    this.failedMore.update((s) => without(s, categoryId));
    this.ctx.menuItems(categoryId, cat.items.length, this.menuQuery()).subscribe({
      next: (page) => {
        this.loadingMore.update((s) => without(s, categoryId));
        if (gen !== this.generation) return;
        this.menu.update((m) =>
          m && {
            ...m,
            categories: m.categories.map((c) => {
              if (c.id !== categoryId) return c;
              const have = new Set(c.items.map((i) => i.id));
              return { ...c, items: [...c.items, ...page.items.filter((i) => !have.has(i.id))], item_count: page.total };
            }),
          },
        );
      },
      error: () => {
        this.loadingMore.update((s) => without(s, categoryId));
        if (gen === this.generation) this.failedMore.update((s) => new Set(s).add(categoryId));
      },
    });
  }

  /** "12 more dishes" — shown under a category while it still has unloaded dishes. */
  protected remaining(c: PublicCategory): number {
    return Math.max(0, (c.item_count ?? c.items.length) - c.items.length);
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

function without(s: ReadonlySet<string>, key: string): ReadonlySet<string> {
  const next = new Set(s);
  next.delete(key);
  return next;
}
