import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';
import {
  FoodClass,
  MenuAddonGroup,
  MenuBranchOverride,
  MenuVariant,
  MenuWindow,
} from '../storefront/storefront.models';

/** Mirrors backend app/schemas/menu.py (admin side). */
export const ALLERGENS = [
  'gluten',
  'dairy',
  'nuts',
  'peanuts',
  'soy',
  'egg',
  'fish',
  'shellfish',
  'sesame',
  'mustard',
  'celery',
] as const;

export interface AdminItem {
  id: string;
  category_id: string;
  subcategory_id: string | null;
  name: string;
  description: string;
  image_url: string | null;
  base_price: string;
  food_class: FoodClass;
  spice_level: number;
  allergens: string[];
  prep_minutes: number;
  is_bestseller: boolean;
  is_todays_special: boolean;
  is_available: boolean;
  is_archived: boolean;
  sort_order: number;
  tax_pct: string;
  tags: string[];
  variants: MenuVariant[];
  addon_groups: MenuAddonGroup[];
  availability: MenuWindow[];
  branch_overrides: MenuBranchOverride[];
}

/** PUT /menu/items/{id}/options — replaces all sizes, extras and serving times. */
export interface ItemOptionsInput {
  variants: { name: string; price: string }[];
  addon_groups: { name: string; min_select: number; max_select: number; addons: { name: string; price: string }[] }[];
  availability: { weekday: number; from_time: string; to_time: string }[];
}

export interface AdminCategory {
  id: string;
  name: string;
  description: string;
  meal_type_ids: string[];
  is_active: boolean;
  is_alcoholic: boolean;
  sort_order: number;
  subcategories: { id: string; name: string; sort_order: number }[];
  item_count: number;
  image_url: string | null;
}

export interface AdminMealType {
  id: string;
  name: string;
  is_active: boolean;
  sort_order: number;
}

export interface AdminMenu {
  meal_types: AdminMealType[];
  categories: AdminCategory[];
  items: AdminItem[];
  alcohol_licensed: boolean;
}

export interface ItemInput {
  category_id: string;
  subcategory_id: string | null;
  name: string;
  description: string;
  base_price: string;
  food_class: FoodClass;
  spice_level: number;
  allergens: string[];
  prep_minutes: number;
  is_bestseller: boolean;
  is_todays_special: boolean;
  tax_pct?: string;
  tags?: string[];
}

@Injectable({ providedIn: 'root' })
export class MenuService {
  private readonly api = inject(ApiService);

  menu(): Observable<AdminMenu> {
    return this.api.get('restaurant/menu');
  }

  createCategory(body: { name: string; description: string; meal_type_ids: string[] }): Observable<AdminMenu> {
    return this.api.post('restaurant/menu/categories', body);
  }
  updateCategory(id: string, body: Partial<Pick<AdminCategory, 'name' | 'description' | 'meal_type_ids' | 'is_active'>>): Observable<AdminMenu> {
    return this.api.patch(`restaurant/menu/categories/${id}`, body);
  }
  deleteCategory(id: string): Observable<AdminMenu> {
    return this.api.delete(`restaurant/menu/categories/${id}`);
  }
  addSubcategory(categoryId: string, name: string): Observable<AdminMenu> {
    return this.api.post(`restaurant/menu/categories/${categoryId}/subcategories`, { name });
  }
  deleteSubcategory(id: string): Observable<AdminMenu> {
    return this.api.delete(`restaurant/menu/subcategories/${id}`);
  }

  createItem(body: ItemInput): Observable<AdminItem> {
    return this.api.post('restaurant/menu/items', body);
  }
  updateItem(id: string, body: Partial<ItemInput>): Observable<AdminItem> {
    return this.api.patch(`restaurant/menu/items/${id}`, body);
  }
  setStock(id: string, available: boolean): Observable<AdminItem> {
    return this.api.patch(`restaurant/menu/items/${id}/stock`, { is_available: available });
  }
  archive(id: string, archived: boolean): Observable<AdminItem> {
    return this.api.post(`restaurant/menu/items/${id}/${archived ? 'archive' : 'restore'}`, {});
  }
  uploadImage(id: string, file: File): Observable<AdminItem> {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return this.api.post(`restaurant/menu/items/${id}/image`, fd);
  }
  setOptions(id: string, body: ItemOptionsInput): Observable<AdminItem> {
    return this.api.put(`restaurant/menu/items/${id}/options`, body);
  }
  setBranchOverride(id: string, branchId: string, body: { is_available: boolean; price_override: string | null }): Observable<AdminItem> {
    return this.api.put(`restaurant/menu/items/${id}/branches/${branchId}`, body);
  }
  removeImage(id: string): Observable<AdminItem> {
    return this.api.delete(`restaurant/menu/items/${id}/image`);
  }
  /** Category card photo on the storefront; without one the template's default photo is shown. */
  uploadCategoryImage(id: string, file: File): Observable<AdminMenu> {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return this.api.post(`restaurant/menu/categories/${id}/image`, fd);
  }
  removeCategoryImage(id: string): Observable<AdminMenu> {
    return this.api.delete(`restaurant/menu/categories/${id}/image`);
  }
}
