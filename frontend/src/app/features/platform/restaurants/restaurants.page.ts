import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';

import { ApiError } from '../../../core/http/api-error';
import { StorefrontApi } from '../../../core/storefront/storefront.api';
import { DiscoveryCard, DiscoveryFilters } from '../../../core/storefront/storefront.models';
import { MapMarker, MapViewComponent } from '../../../shared/ui/map/map-view.component';
import { RestaurantCardComponent } from '../../../shared/ui/restaurant-card/restaurant-card.component';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

const PAGE_SIZE = 12;

/** Restaurant discovery (PRD §2.1): name, location, cuisine, type, open now, near me. Filters live in the URL. */
@Component({
  selector: 'wl-restaurants-page',
  imports: [RestaurantCardComponent, MapViewComponent, LoadingStateComponent, ErrorStateComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './restaurants.page.html',
  styleUrl: './restaurants.page.scss',
})
export class RestaurantsPage implements OnInit {
  private readonly api = inject(StorefrontApi);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly filters = signal<DiscoveryFilters>({ cities: [], cuisines: [], restaurant_types: [] });
  protected readonly items = signal<DiscoveryCard[]>([]);
  protected readonly total = signal(0);
  protected readonly page = signal(1);
  protected readonly loading = signal(true);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly view = signal<'list' | 'map'>('list');
  protected readonly geoError = signal<string | null>(null);
  protected readonly locating = signal(false);
  protected readonly highlighted = signal<string | null>(null);

  // Current filters (mirrors the URL)
  protected readonly q = signal('');
  protected readonly city = signal('');
  protected readonly cuisine = signal('');
  protected readonly type = signal('');
  protected readonly openNow = signal(false);
  protected readonly coords = signal<{ lat: number; lng: number } | null>(null);
  protected readonly radius = signal<number | null>(null);

  protected readonly markers = computed<MapMarker[]>(() =>
    this.items()
      .filter((r) => r.lat && r.lng)
      .map((r) => ({
        id: r.id,
        lat: +r.lat!,
        lng: +r.lng!,
        title: r.name,
        subtitle: [r.city, r.open_now ? 'Open now' : 'Closed'].filter(Boolean).join(' · '),
        link: `/r/${r.slug}`,
      })),
  );
  protected readonly hasMore = computed(() => this.items().length < this.total());
  protected readonly activeFilters = computed(
    () => !!(this.q() || this.city() || this.cuisine() || this.type() || this.openNow() || this.coords()),
  );
  private search?: Subscription;

  ngOnInit(): void {
    this.api.filters().subscribe({ next: (f) => this.filters.set(f), error: () => undefined });
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((p) => {
      this.q.set(p.get('q') ?? '');
      this.city.set(p.get('city') ?? '');
      this.cuisine.set(p.get('cuisine') ?? '');
      this.type.set(p.get('type') ?? '');
      this.openNow.set(p.get('open') === '1');
      const lat = Number(p.get('lat'));
      const lng = Number(p.get('lng'));
      this.coords.set(p.has('lat') && p.has('lng') && !isNaN(lat) && !isNaN(lng) ? { lat, lng } : null);
      this.radius.set(p.get('radius') ? Number(p.get('radius')) : null);
      if (p.get('near') === '1' && !this.coords()) {
        this.nearMe();
        return;
      }
      this.fetch(1);
    });
  }

  protected setFilter(key: 'q' | 'city' | 'cuisine' | 'type' | 'open' | 'radius', value: string | boolean | null): void {
    const v = value === true ? '1' : value === false || value === '' ? null : value;
    void this.router.navigate([], { relativeTo: this.route, queryParams: { [key]: v }, queryParamsHandling: 'merge' });
  }

  protected clearAll(): void {
    void this.router.navigate([], { relativeTo: this.route, queryParams: {} });
  }

  protected nearMe(): void {
    if (!('geolocation' in navigator)) {
      this.geoError.set('Your browser cannot share its location.');
      return;
    }
    this.locating.set(true);
    this.geoError.set(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        this.locating.set(false);
        const lat = Math.round(pos.coords.latitude * 1e4) / 1e4; // ~10 m: enough for sorting, less precise to share
        const lng = Math.round(pos.coords.longitude * 1e4) / 1e4;
        void this.router.navigate([], {
          relativeTo: this.route,
          queryParams: { lat, lng, near: null },
          queryParamsHandling: 'merge',
        });
      },
      () => {
        this.locating.set(false);
        this.geoError.set('Location permission was not given. Search by city instead.');
        this.fetch(1);
      },
      { timeout: 10_000, maximumAge: 300_000 },
    );
  }

  protected clearLocation(): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { lat: null, lng: null, radius: null, near: null },
      queryParamsHandling: 'merge',
    });
  }

  protected loadMore(): void {
    this.fetch(this.page() + 1);
  }

  private fetch(page: number): void {
    this.search?.unsubscribe();
    this.loading.set(true);
    this.error.set(null);
    const c = this.coords();
    this.search = this.api
      .discover({
        q: this.q() || null,
        city: this.city() || null,
        cuisine: this.cuisine() || null,
        type: this.type() || null,
        open_now: this.openNow() || null,
        lat: c?.lat ?? null,
        lng: c?.lng ?? null,
        radius_km: c ? this.radius() : null,
        page,
        page_size: PAGE_SIZE,
      })
      .subscribe({
        next: (r) => {
          this.items.update((prev) => (page === 1 ? r.items : [...prev, ...r.items]));
          this.total.set(r.total);
          this.page.set(page);
          this.loading.set(false);
        },
        error: (e: ApiError) => {
          this.error.set(e);
          this.loading.set(false);
        },
      });
  }
}
