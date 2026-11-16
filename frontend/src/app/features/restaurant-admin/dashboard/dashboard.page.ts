import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { RestaurantMe } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/**
 * Phase 2 dashboard: approval status, plan/trial and branches.
 * KPIs (revenue, orders, tables, queue…) arrive with their modules (PRD §15).
 */
@Component({
  selector: 'wl-restaurant-dashboard',
  imports: [DatePipe, MatButtonModule, MatIconModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './dashboard.page.html',
  styleUrl: './dashboard.page.scss',
})
export class DashboardPage implements OnInit {
  private readonly tenancy = inject(TenancyService);
  protected readonly auth = inject(AuthService);

  protected readonly data = signal<RestaurantMe | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly permissionCount = computed(() => Object.keys(this.auth.activeTenant()?.permissions ?? {}).length);
  protected readonly trialDaysLeft = computed(() => {
    const end = this.data()?.subscription?.trial_ends_at;
    if (!end) return null;
    return Math.max(0, Math.ceil((Date.parse(end) - Date.now()) / 86_400_000));
  });

  protected readonly setupSteps = [
    { icon: 'storefront', label: 'Complete your profile', hint: 'About, hours, contacts', phase: 3 },
    { icon: 'palette', label: 'Add logo & colours', hint: 'Or keep the default theme', phase: 3 },
    { icon: 'photo_library', label: 'Upload up to 5 photos', hint: 'Shown in your gallery', phase: 3 },
    { icon: 'restaurant_menu', label: 'Build your menu', hint: 'Categories and dishes', phase: 4 },
    { icon: 'table_restaurant', label: 'Add tables', hint: 'Sections and capacity', phase: 5 },
  ];

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
  }
}
