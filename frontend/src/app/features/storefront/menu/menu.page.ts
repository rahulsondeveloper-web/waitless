import { ViewportScroller } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';

import { ApiError } from '../../../core/http/api-error';
import { PublicCategory, PublicMenu, formatPrice } from '../../../core/storefront/storefront.models';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

const FOOD_LABEL = { veg: 'Vegetarian', non_veg: 'Non-vegetarian', egg: 'Contains egg' } as const;

/** Restaurant menu (PRD §6 Menu, §7.3). Ordering arrives in Phase 7. */
@Component({
  selector: 'wl-storefront-menu',
  imports: [LoadingStateComponent, ErrorStateComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './menu.page.html',
  styleUrl: './menu.page.scss',
})
export class StorefrontMenuPage implements OnInit {
  private readonly ctx = inject(TenantContextService);
  private readonly scroller = inject(ViewportScroller);

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
  }

  protected load(): void {
    this.error.set(null);
    this.ctx.menu().subscribe({ next: (m) => this.menu.set(m), error: (e: ApiError) => this.error.set(e) });
  }

  protected price(v: string): string {
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
