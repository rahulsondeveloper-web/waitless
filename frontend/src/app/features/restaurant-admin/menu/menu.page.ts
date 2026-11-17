import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { RouterLink } from '@angular/router';
import { Observable, filter } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { AdminItem, AdminMenu, MenuService } from '../../../core/restaurant/menu.service';
import { formatPrice } from '../../../core/storefront/storefront.models';
import { ConfirmData, ConfirmDialogComponent } from '../../../shared/ui/confirm-dialog/confirm-dialog.component';
import { checkImageFile, takeFile } from '../../../shared/ui/image-check';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { CategoryDialogComponent, CategoryDialogData } from './category-dialog.component';
import { ItemDialogComponent, ItemDialogData } from './item-dialog.component';

/** Menu management (PRD §7): categories, subcategories, dishes, photos, sold-out, archive. */
@Component({
  selector: 'wl-menu-admin-page',
  imports: [RouterLink, MatButtonModule, MatIconModule, MatSlideToggleModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './menu.page.html',
  styleUrl: './menu.page.scss',
})
export class MenuAdminPage implements OnInit {
  private readonly svc = inject(MenuService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  protected readonly auth = inject(AuthService);

  protected readonly menu = signal<AdminMenu | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly mealFilter = signal<string | null>(null);
  protected readonly selectedId = signal<string | null>(null);
  protected readonly showArchived = signal(false);
  protected readonly busy = signal<string | null>(null);

  protected readonly categories = computed(() => {
    const m = this.menu();
    if (!m) return [];
    const meal = this.mealFilter();
    return m.categories.filter((c) => !meal || c.meal_type_ids.includes(meal));
  });
  protected readonly selected = computed(() => this.menu()?.categories.find((c) => c.id === this.selectedId()) ?? null);
  protected readonly items = computed(() =>
    (this.menu()?.items ?? []).filter(
      (i) => i.category_id === this.selectedId() && (this.showArchived() || !i.is_archived),
    ),
  );
  protected readonly subName = computed(() => {
    const map = new Map<string, string>();
    for (const c of this.menu()?.categories ?? []) for (const s of c.subcategories) map.set(s.id, s.name);
    return map;
  });
  protected readonly totalDishes = computed(() => (this.menu()?.items ?? []).filter((i) => !i.is_archived).length);

  ngOnInit(): void {
    this.svc.menu().subscribe({
      next: (m) => {
        this.setMenu(m);
        // Start on the first category that has dishes, else the first one.
        this.selectedId.set((m.categories.find((c) => c.item_count) ?? m.categories[0])?.id ?? null);
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }

  protected price(v: string): string {
    return formatPrice(v);
  }

  // ---------- categories ----------

  protected newCategory(): void {
    this.openCategoryDialog(null);
  }

  protected editCategory(): void {
    this.openCategoryDialog(this.selected());
  }

  private openCategoryDialog(category: CategoryDialogData['category']): void {
    const m = this.menu();
    if (!m) return;
    const data: CategoryDialogData = { category, mealTypes: m.meal_types, defaultMealTypeId: this.mealFilter() };
    this.dialog
      .open<CategoryDialogComponent, CategoryDialogData, AdminMenu>(CategoryDialogComponent, { data, width: '480px' })
      .afterClosed()
      .pipe(filter((r): r is AdminMenu => !!r))
      .subscribe((menu) => {
        const before = new Set(this.menu()?.categories.map((c) => c.id));
        this.setMenu(menu);
        const created = menu.categories.find((c) => !before.has(c.id));
        if (created) this.selectedId.set(created.id);
        this.snack.open('Category saved.', undefined, { duration: 2000 });
      });
  }

  protected toggleCategory(active: boolean): void {
    const c = this.selected();
    if (!c) return;
    this.run(`cat-${c.id}`, this.svc.updateCategory(c.id, { is_active: active }), (m) => this.setMenu(m as AdminMenu));
  }

  protected deleteCategory(): void {
    const c = this.selected();
    if (!c) return;
    this.confirm({ title: `Delete "${c.name}"?`, message: 'The category is removed.', confirm: 'Delete', danger: true }, () =>
      this.run(`cat-${c.id}`, this.svc.deleteCategory(c.id), (m) => {
        this.setMenu(m as AdminMenu);
        this.selectedId.set(this.categories()[0]?.id ?? null);
      }),
    );
  }

  protected addSubcategory(input: HTMLInputElement): void {
    const c = this.selected();
    const name = input.value.trim();
    if (!c || !name) return;
    this.run(`sub-${c.id}`, this.svc.addSubcategory(c.id, name), (m) => {
      this.setMenu(m as AdminMenu);
      input.value = '';
    });
  }

  protected removeSubcategory(id: string, name: string): void {
    this.confirm(
      { title: `Remove "${name}"?`, message: 'Dishes in it stay in the category.', confirm: 'Remove' },
      () => this.run(`sub-${id}`, this.svc.deleteSubcategory(id), (m) => this.setMenu(m as AdminMenu)),
    );
  }

  // ---------- items ----------

  protected openItem(item: AdminItem | null): void {
    const m = this.menu();
    const categoryId = this.selectedId();
    if (!m || !categoryId) return;
    const data: ItemDialogData = { item, categories: m.categories.filter((c) => !c.is_alcoholic || m.alcohol_licensed), categoryId };
    this.dialog
      .open<ItemDialogComponent, ItemDialogData, AdminItem>(ItemDialogComponent, { data, width: '640px', maxWidth: '96vw' })
      .afterClosed()
      .pipe(filter((r): r is AdminItem => !!r))
      .subscribe((saved) => {
        this.upsertItem(saved);
        this.snack.open(item ? 'Dish updated.' : 'Dish added.', undefined, { duration: 2000 });
      });
  }

  protected setStock(item: AdminItem, available: boolean): void {
    this.run(item.id, this.svc.setStock(item.id, available), (i) => this.upsertItem(i as AdminItem));
  }

  protected archive(item: AdminItem, archived: boolean): void {
    this.run(item.id, this.svc.archive(item.id, archived), (i) => this.upsertItem(i as AdminItem));
  }

  protected uploadImage(item: AdminItem, event: Event): void {
    const file = takeFile(event);
    const problem = checkImageFile(file);
    if (problem) return void this.snack.open(problem, 'OK', { duration: 4000 });
    this.run(item.id, this.svc.uploadImage(item.id, file!), (i) => this.upsertItem(i as AdminItem));
  }

  protected removeImage(item: AdminItem): void {
    this.run(item.id, this.svc.removeImage(item.id), (i) => this.upsertItem(i as AdminItem));
  }

  // ---------- helpers ----------

  private setMenu(m: AdminMenu): void {
    this.menu.set(m);
  }

  private upsertItem(item: AdminItem): void {
    this.menu.update((m) => {
      if (!m) return m;
      const exists = m.items.some((i) => i.id === item.id);
      const items = exists ? m.items.map((i) => (i.id === item.id ? item : i)) : [...m.items, item];
      const counts = new Map<string, number>();
      for (const i of items) if (!i.is_archived) counts.set(i.category_id, (counts.get(i.category_id) ?? 0) + 1);
      return { ...m, items, categories: m.categories.map((c) => ({ ...c, item_count: counts.get(c.id) ?? 0 })) };
    });
  }

  private confirm(data: ConfirmData, then: () => void): void {
    this.dialog.open(ConfirmDialogComponent, { data, width: '400px' }).afterClosed().pipe(filter(Boolean)).subscribe(then);
  }

  private run<T>(key: string, obs: Observable<T>, done: (v: T) => void): void {
    this.busy.set(key);
    obs.subscribe({
      next: (v) => {
        this.busy.set(null);
        done(v);
      },
      error: (e: ApiError) => {
        this.busy.set(null);
        this.snack.open(e.message, 'Dismiss', { duration: 6000 });
      },
    });
  }
}
