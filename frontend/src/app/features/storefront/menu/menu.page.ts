import { ViewportScroller } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';

import { ActivatedRoute, RouterLink } from '@angular/router';

import { ApiError } from '../../../core/http/api-error';
import { CartLine, CartService } from '../../../core/ordering/cart.service';
import { OrderingService, itemPrice, unavailableReason } from '../../../core/ordering/ordering.service';
import { PublicCategory, PublicItem, PublicMenu, formatPrice } from '../../../core/storefront/storefront.models';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { DishPickerComponent } from './dish-picker.component';

const FOOD_LABEL = { veg: 'Vegetarian', non_veg: 'Non-vegetarian', egg: 'Contains egg' } as const;

/** Restaurant menu (PRD §6 Menu, §7.3) with ordering (PRD §13): pick options → cart. */
@Component({
  selector: 'wl-storefront-menu',
  imports: [LoadingStateComponent, ErrorStateComponent, EmptyStateComponent, DishPickerComponent, RouterLink],
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

  protected jump(id: string): void {
    this.scroller.setOffset([0, 140]);
    this.scroller.scrollToAnchor(`cat-${id}`);
  }

  protected spice(level: number): string {
    return '🌶'.repeat(level);
  }
}
