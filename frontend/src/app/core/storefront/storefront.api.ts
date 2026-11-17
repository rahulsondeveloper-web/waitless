import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';
import {
  ContactRequest,
  DiscoveryFilters,
  DiscoveryPage,
  DiscoveryQuery,
  Gallery,
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
  menu(slug: string): Observable<PublicMenu> {
    return this.api.get(`public/restaurants/${encodeURIComponent(slug)}/menu`);
  }
  gallery(slug: string): Observable<Gallery> {
    return this.api.get(`public/restaurants/${encodeURIComponent(slug)}/gallery`);
  }

  // Owner preview (signed-in staff of that restaurant; works before publishing)
  previewStorefront(): Observable<Storefront> {
    return this.api.get('restaurant/storefront');
  }
  previewMenu(): Observable<PublicMenu> {
    return this.api.get('restaurant/storefront/menu');
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
