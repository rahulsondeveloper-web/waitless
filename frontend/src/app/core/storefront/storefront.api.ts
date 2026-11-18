import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';
import {
  ContactRequest,
  DiscoveryFilters,
  DiscoveryPage,
  DiscoveryQuery,
  Gallery,
  MenuQuery,
  PublicItemsPage,
  PublicMenu,
  Storefront,
} from './storefront.models';

/** Public (anonymous) storefront & discovery endpoints, plus the owner preview equivalents. */
@Injectable({ providedIn: 'root' })
export class StorefrontApi {
  private readonly api = inject(ApiService);

  storefront(slug: string): Observable<Storefront> {
    return this.api.get(`public/restaurants/${encodeURIComponent(slug)}`);
  }
  menu(slug: string, query: MenuQuery = {}): Observable<PublicMenu> {
    return this.api.get(`public/restaurants/${encodeURIComponent(slug)}/menu`, menuParams(query));
  }
  menuItems(slug: string, categoryId: string, offset: number, query: MenuQuery = {}): Observable<PublicItemsPage> {
    return this.api.get(
      `public/restaurants/${encodeURIComponent(slug)}/menu/categories/${categoryId}/items`,
      menuParams({ ...query, offset }),
    );
  }
  gallery(slug: string): Observable<Gallery> {
    return this.api.get(`public/restaurants/${encodeURIComponent(slug)}/gallery`);
  }

  // Owner preview (signed-in staff of that restaurant; works before publishing)
  previewStorefront(): Observable<Storefront> {
    return this.api.get('restaurant/storefront');
  }
  previewMenuItems(categoryId: string, offset: number, query: MenuQuery = {}): Observable<PublicItemsPage> {
    return this.api.get(`restaurant/storefront/menu/categories/${categoryId}/items`, menuParams({ ...query, offset }));
  }
  previewMenu(query: MenuQuery = {}): Observable<PublicMenu> {
    return this.api.get('restaurant/storefront/menu', menuParams(query));
  }
  previewGallery(): Observable<Gallery> {
    return this.api.get('restaurant/gallery');
  }

  discover(query: DiscoveryQuery): Observable<DiscoveryPage> {
    return this.api.get('public/restaurants', query as Record<string, string | number | boolean | null | undefined>);
  }
  filters(): Observable<DiscoveryFilters> {
    return this.api.get('public/discovery/filters');
  }
  contact(body: ContactRequest): Observable<{ received: boolean; message: string }> {
    return this.api.post('public/contact', body);
  }
}

/** Only the filters that are set (the full menu is returned when nothing is passed). */
function menuParams(q: MenuQuery & { offset?: number }): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  if (q.limit) out['limit'] = q.limit;
  if (q.offset) out['offset'] = q.offset;
  if (q.veg) out['veg'] = true;
  if (q.q?.trim()) out['q'] = q.q.trim();
  return out;
}
