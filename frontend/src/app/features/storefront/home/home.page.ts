import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, of, switchMap } from 'rxjs';

import { BookingsService, WaitTime } from '../../../core/bookings/bookings.service';

import { TenantContextService } from '../../../core/storefront/tenant-context.service';

/** Restaurant homepage (PRD §6 Home). */
@Component({
  selector: 'wl-storefront-home',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './home.page.html',
  styleUrl: './home.page.scss',
})
export class StorefrontHomePage {
  protected readonly ctx = inject(TenantContextService);
  protected readonly r = this.ctx.restaurant;
  protected readonly branch = this.ctx.primaryBranch;
  protected readonly gallery = toSignal(this.ctx.gallery().pipe(catchError(() => of(null))), { initialValue: null });
  protected readonly photos = computed(() => this.gallery()?.items.slice(0, 3) ?? []);
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
}
