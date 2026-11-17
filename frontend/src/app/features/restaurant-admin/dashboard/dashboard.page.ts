import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { PublishChecklist } from '../../../core/restaurant/restaurant.models';
import { Dashboard, OperationsService } from '../../../core/restaurant/operations.service';
import { RestaurantService } from '../../../core/restaurant/restaurant.service';
import { RestaurantMe } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { formatPrice } from '../../../core/storefront/storefront.models';

/**
 * Phase 2 dashboard: approval status, plan/trial and branches.
 * KPIs (revenue, orders, tables, queue…) arrive with their modules (PRD §15).
 */
@Component({
  selector: 'wl-restaurant-dashboard',
  imports: [DatePipe, RouterLink, MatButtonModule, MatIconModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './dashboard.page.html',
  styleUrl: './dashboard.page.scss',
})
export class DashboardPage implements OnInit {
  private readonly tenancy = inject(TenancyService);
  private readonly restaurant = inject(RestaurantService);
  private readonly ops = inject(OperationsService);
  private readonly snack = inject(MatSnackBar);
  protected readonly auth = inject(AuthService);

  protected readonly data = signal<RestaurantMe | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly permissionCount = computed(() => Object.keys(this.auth.activeTenant()?.permissions ?? {}).length);
  protected readonly trialDaysLeft = computed(() => {
    const end = this.data()?.subscription?.trial_ends_at;
    if (!end) return null;
    return Math.max(0, Math.ceil((Date.parse(end) - Date.now()) / 86_400_000));
  });

  protected readonly checklist = signal<PublishChecklist | null>(null);
  protected readonly kpis = signal<Dashboard | null>(null);
  protected readonly price = (v: string | number) => formatPrice(v);
  protected readonly publishing = signal(false);
  protected readonly canPublish = computed(() => this.auth.hasPermission('restaurant.profile.manage'));
  protected readonly remaining = computed(
    () => this.checklist()?.items.filter((i) => i.required && !i.done).length ?? 0,
  );

  /** Where each checklist item is fixed. */
  protected readonly links: Record<string, { path: string; icon: string } | undefined> = {
    description: { path: 'profile', icon: 'edit_note' },
    contact: { path: 'profile', icon: 'call' },
    location: { path: 'profile', icon: 'location_on' },
    hours: { path: 'profile', icon: 'schedule' },
    cover: { path: 'branding', icon: 'image' },
    logo: { path: 'branding', icon: 'palette' },
    gallery: { path: 'gallery', icon: 'photo_library' },
    menu: { path: 'menu', icon: 'restaurant_menu' },
    tables: { path: 'tables', icon: 'table_restaurant' },
  };

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.error.set(null);
    this.data.set(null);
    this.tenancy.restaurantMe().subscribe({
      next: (d) => this.data.set(d),
      error: (e: ApiError) => this.error.set(e),
    });
    if (this.auth.hasPermission('tables.operate')) {
      this.ops.dashboard().subscribe({ next: (k) => this.kpis.set(k), error: () => this.kpis.set(null) });
    }
    if (this.auth.hasPermission('restaurant.profile.view')) {
      this.restaurant.checklist().subscribe({ next: (c) => this.checklist.set(c), error: () => this.checklist.set(null) });
    }
  }

  protected togglePublished(): void {
    const target = !this.checklist()?.is_published;
    this.publishing.set(true);
    this.restaurant.publish(target).subscribe({
      next: (c) => {
        this.checklist.set(c);
        this.publishing.set(false);
        this.snack.open(target ? 'Your storefront is live!' : 'Storefront hidden from guests.', undefined, {
          duration: 3000,
        });
        this.tenancy.restaurantMe().subscribe((d) => this.data.set(d));
      },
      error: (e: ApiError) => {
        this.publishing.set(false);
        this.snack.open(e.message, 'Dismiss', { duration: 5000 });
      },
    });
  }
}
