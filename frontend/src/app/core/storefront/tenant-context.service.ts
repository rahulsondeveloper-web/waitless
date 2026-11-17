import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, Subscription, catchError, map, of, shareReplay, tap, throwError } from 'rxjs';

import { AuthService } from '../auth/auth.service';
import { ApiError } from '../http/api-error';
import { ThemeService } from '../theme/theme.service';
import { StorefrontApi } from './storefront.api';
import { Gallery, PublicMenu, Storefront } from './storefront.models';

export type StorefrontStatus = 'idle' | 'loading' | 'ready' | 'not_found' | 'error';

/**
 * The restaurant currently shown under /r/:slug (PRD §2.2, §20).
 *
 * Isolation rules:
 *  - entering a different slug clears every piece of tenant data *before* loading the next one;
 *  - responses that arrive for a previous slug are dropped (in-flight requests are cancelled);
 *  - menu/gallery caches are keyed by slug, so restaurant A's data can never render on B's page.
 */
@Injectable({ providedIn: 'root' })
export class TenantContextService {
  private readonly api = inject(StorefrontApi);
  private readonly theme = inject(ThemeService);
  private readonly auth = inject(AuthService);

  private readonly _slug = signal<string | null>(null);
  private readonly _restaurant = signal<Storefront | null>(null);
  private readonly _status = signal<StorefrontStatus>('idle');
  private readonly _preview = signal(false);
  private readonly _error = signal<ApiError | null>(null);
  private loadSub?: Subscription;
  private menu$?: { slug: string; obs: Observable<PublicMenu> };
  private gallery$?: { slug: string; obs: Observable<Gallery> };

  readonly slug = this._slug.asReadonly();
  readonly restaurant = this._restaurant.asReadonly();
  readonly status = this._status.asReadonly();
  /** True when an owner is looking at their own unpublished storefront. */
  readonly preview = this._preview.asReadonly();
  readonly error = this._error.asReadonly();
  readonly primaryBranch = computed(() => {
    const r = this._restaurant();
    return r?.branches.find((b) => b.is_primary) ?? r?.branches[0] ?? null;
  });

  enter(slug: string): void {
    const clean = slug.toLowerCase();
    if (clean === this._slug() && this._status() !== 'error') return;
    this.clear();
    this._slug.set(clean);
    this._status.set('loading');

    this.loadSub = this.api
      .storefront(clean)
      .pipe(
        map((r) => ({ r, preview: false })),
        catchError((e: ApiError) => {
          // Owners can preview their own restaurant before it is published.
          if (e.status === 404 && this.isOwnRestaurant(clean)) {
            return this.api.previewStorefront().pipe(map((r) => ({ r, preview: true })));
          }
          return throwError(() => e);
        }),
      )
      .subscribe({
        next: ({ r, preview }) => {
          if (this._slug() !== clean) return; // a newer restaurant was entered meanwhile
          this._restaurant.set(r);
          this._preview.set(preview);
          this.theme.applyBranding(r.branding);
          this._status.set('ready');
        },
        error: (e: ApiError) => {
          if (this._slug() !== clean) return;
          this._error.set(e);
          this._status.set(e.status === 404 ? 'not_found' : 'error');
        },
      });
  }

  leave(): void {
    this.clear();
    this.theme.reset();
  }

  retry(): void {
    const s = this._slug();
    if (s) {
      this._slug.set(null);
      this.enter(s);
    }
  }

  menu(): Observable<PublicMenu> {
    const slug = this._slug();
    if (!slug) return throwError(() => new ApiError(0, 'NO_RESTAURANT', 'No restaurant selected.'));
    if (this.menu$?.slug !== slug) {
      const src = this._preview() ? this.api.previewMenu() : this.api.menu(slug);
      this.menu$ = { slug, obs: src.pipe(shareReplay(1)) };
    }
    return this.menu$.obs.pipe(tap(() => this.assertStill(slug)));
  }

  gallery(): Observable<Gallery> {
    const slug = this._slug();
    if (!slug) return of({ items: [], max_photos: 5 });
    if (this.gallery$?.slug !== slug) {
      const src = this._preview() ? this.api.previewGallery() : this.api.gallery(slug);
      this.gallery$ = { slug, obs: src.pipe(shareReplay(1)) };
    }
    return this.gallery$.obs.pipe(tap(() => this.assertStill(slug)));
  }

  private assertStill(slug: string): void {
    if (this._slug() !== slug) throw new ApiError(0, 'STALE_TENANT', 'Restaurant changed.');
  }

  private isOwnRestaurant(slug: string): boolean {
    return this.auth.activeTenant()?.tenant_slug?.toLowerCase() === slug;
  }

  private clear(): void {
    this.loadSub?.unsubscribe();
    this.loadSub = undefined;
    this.menu$ = undefined;
    this.gallery$ = undefined;
    this._slug.set(null);
    this._restaurant.set(null);
    this._preview.set(false);
    this._error.set(null);
    this._status.set('idle');
  }
}
