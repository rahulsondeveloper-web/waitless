import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';
import {
  Branch,
  Page,
  RestaurantAdminRow,
  RestaurantMe,
  RestaurantRegistration,
  SlugAvailability,
  StatusAction,
  Tenant,
  TenantStatus,
} from './tenancy.models';

@Injectable({ providedIn: 'root' })
export class TenancyService {
  private readonly api = inject(ApiService);

  // Public
  register(body: RestaurantRegistration): Observable<{ tenant: Tenant; message: string }> {
    return this.api.post('public/restaurants/register', body);
  }

  slugAvailability(params: { slug?: string; name?: string; city?: string }): Observable<SlugAvailability> {
    return this.api.get('public/slug-availability', params);
  }

  // Restaurant admin
  restaurantMe(): Observable<RestaurantMe> {
    return this.api.get('restaurant/me');
  }

  branches(): Observable<Branch[]> {
    return this.api.get('restaurant/branches');
  }

  // Super Admin
  listRestaurants(params: {
    status?: TenantStatus | null;
    q?: string | null;
    page?: number;
    page_size?: number;
  }): Observable<Page<RestaurantAdminRow>> {
    return this.api.get('super-admin/restaurants', params);
  }

  changeStatus(id: string, action: StatusAction, reason?: string | null): Observable<RestaurantAdminRow> {
    return this.api.patch(`super-admin/restaurants/${id}/status`, { action, reason: reason || null });
  }
}
