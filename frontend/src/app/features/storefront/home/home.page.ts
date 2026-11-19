import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, of, switchMap } from 'rxjs';

import { BookingsService, WaitTime } from '../../../core/bookings/bookings.service';

import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { GuestServiceApi } from '../../../core/ordering/guest-service.service';
import { MapMarker, MapViewComponent } from '../../../shared/ui/map/map-view.component';
import { PopupComponent } from '../../../shared/ui/popup/popup.component';
import { JoinQueuePopupComponent } from './join-queue-popup.component';
import { WifiButtonComponent } from './wifi-button.component';

/** Restaurant homepage (PRD §6 Home). */
@Component({
  selector: 'wl-storefront-home',
  imports: [RouterLink, WifiButtonComponent, PopupComponent, MapViewComponent, JoinQueuePopupComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './home.page.html',
  styleUrl: './home.page.scss',
})
export class StorefrontHomePage {
  protected readonly ctx = inject(TenantContextService);
  protected readonly r = this.ctx.restaurant;
  protected readonly branch = this.ctx.primaryBranch;
  /** Reloads when the restaurant changes its photos (ctx.version bumps on the server push). */
  protected readonly gallery = toSignal(
    toObservable(this.ctx.version).pipe(switchMap(() => this.ctx.gallery().pipe(catchError(() => of(null))))),
    { initialValue: null },
  );
  protected readonly photos = computed(() => this.gallery()?.items.slice(0, 3) ?? []);
  private readonly service = inject(GuestServiceApi);
  /** Public reviews (refreshed when the restaurant's data changes, e.g. a new review or one hidden). */
  protected readonly reviews = toSignal(
    toObservable(this.ctx.version).pipe(
      switchMap(() => {
        const slug = this.ctx.slug();
        return slug && !this.ctx.preview() ? this.service.publicReviews(slug).pipe(catchError(() => of(null))) : of(null);
      }),
    ),
    { initialValue: null },
  );

  protected stars(n: number): string {
    const full = Math.round(n);
    return '★'.repeat(full) + '☆'.repeat(Math.max(0, 5 - full));
  }

  protected date(iso: string): string {
    return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
  }
  private readonly bookings = inject(BookingsService);
  /** Live-ish wait for the main branch (PRD §12 "estimated wait time"); hidden when unavailable. */
  protected readonly wait = toSignal(
    toObservable(this.branch).pipe(
      switchMap((b) => {
        const slug = this.ctx.slug();
        if (!b || !slug || this.ctx.preview()) return of(null);
        return this.bookings.waitTime(slug, b.id).pipe(catchError(() => of(null as WaitTime | null)));
      }),
    ),
    { initialValue: null },
  );
  protected readonly mapsUrl = computed(() => {
    const b = this.branch();
    if (!b) return null;
    const q = b.lat && b.lng ? `${b.lat},${b.lng}` : `${b.address_line}, ${b.city}`;
    return `https://www.openstreetmap.org/search?query=${encodeURIComponent(q)}`;
  });
  protected readonly directionsUrl = computed(() => {
    const b = this.branch();
    if (!b) return null;
    const q = b.lat && b.lng ? `${b.lat},${b.lng}` : `${b.address_line}, ${b.city}, ${b.state}`;
    return `https://www.openstreetmap.org/directions?to=${encodeURIComponent(q)}`;
  });

  /** Which pop-up is open: the map ("Location") or the guests question ("Join the queue"). */
  protected readonly popup = signal<'location' | 'queue' | null>(null);
  /** Every branch with a pin on the map; the main branch is highlighted. */
  protected readonly markers = computed<MapMarker[]>(() =>
    (this.r()?.branches ?? [])
      .filter((b) => b.lat && b.lng)
      .map((b) => ({ id: b.id, lat: +b.lat!, lng: +b.lng!, title: b.name, subtitle: `${b.address_line}, ${b.city}` })),
  );
}
