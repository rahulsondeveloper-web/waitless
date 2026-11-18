import { HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { catchError, of, tap, throwError } from 'rxjs';

/**
 * Browser cache for the public storefront reads (profile, branding, gallery, menu, menu batches).
 *
 * A response is kept (memory + localStorage) and served without calling the API again until:
 *  - the restaurant changes something → the server pushes Socket.IO `storefront.changed`
 *    (TenantContextService calls `invalidate(slug)`), or
 *  - the app was reloaded / the socket reconnected (a change may have been missed), or
 *  - it is older than MAX_AGE_MS (safety net when the socket is not connected).
 * Then the API is asked again *with* the ETag: unchanged data costs an empty 304, changed data a 200.
 */

const MAX_AGE_MS = 10 * 60_000;
const MAX_ENTRIES = 60;
const MAX_STORED_CHARS = 1_500_000;
const STORE_PREFIX = 'wl.http.';

/** Only these GETs are cached (never availability, queue, tables or anything personal). */
const CACHEABLE =
  /\/api\/v1\/public\/restaurants\/([a-z0-9-]+)(?:\/(?:menu(?:\/categories\/[0-9a-f-]+\/items)?|gallery|branding))?(?:\?|$)/i;

interface Entry {
  etag: string | null;
  body: unknown;
  /** when the server last confirmed it in this app run (0 = loaded from localStorage, not confirmed yet) */
  checkedAt: number;
  slug: string;
}

export function cacheSlug(url: string): string | null {
  return CACHEABLE.exec(url)?.[1]?.toLowerCase() ?? null;
}

@Injectable({ providedIn: 'root' })
export class HttpCacheService {
  private readonly mem = new Map<string, Entry>();
  /** slug → time of the last "changed" push (entries checked before it are stale) */
  private readonly changedAt = new Map<string, number>();
  private allStaleAt = 0;

  get(key: string): Entry | null {
    let e = this.mem.get(key) ?? null;
    if (!e) {
      e = this.restore(key);
      if (e) this.mem.set(key, e);
    }
    return e;
  }

  /** Fresh = confirmed by the server in this app run, after the last change push, and not too old. */
  isFresh(e: Entry, now = Date.now()): boolean {
    return (
      e.checkedAt > 0 &&
      e.checkedAt >= (this.changedAt.get(e.slug) ?? 0) &&
      e.checkedAt >= this.allStaleAt &&
      now - e.checkedAt < MAX_AGE_MS
    );
  }

  put(key: string, slug: string, etag: string | null, body: unknown): void {
    this.mem.delete(key); // re-insert = most recently used
    this.mem.set(key, { etag, body, checkedAt: Date.now(), slug });
    while (this.mem.size > MAX_ENTRIES) this.mem.delete(this.mem.keys().next().value as string);
    if (etag && !/[?&]q=/.test(key)) this.store(key, { etag, body, slug });
  }

  /** The server answered 304: the kept copy is current again. */
  confirm(key: string): void {
    const e = this.mem.get(key);
    if (e) e.checkedAt = Date.now();
  }

  /** The restaurant changed something: check every kept response of it again (ETag makes it cheap). */
  invalidate(slug: string): void {
    this.changedAt.set(slug.toLowerCase(), Date.now() + 1);
  }

  /** A change push may have been missed (socket reconnected). */
  markAllStale(): void {
    this.allStaleAt = Date.now() + 1;
  }

  private restore(key: string): Entry | null {
    try {
      const raw = localStorage.getItem(STORE_PREFIX + key);
      if (!raw) return null;
      const v = JSON.parse(raw) as { etag: string; body: unknown; slug: string };
      return { etag: v.etag, body: v.body, slug: v.slug, checkedAt: 0 };
    } catch {
      return null;
    }
  }

  private store(key: string, v: { etag: string; body: unknown; slug: string }): void {
    try {
      const raw = JSON.stringify(v);
      if (raw.length > MAX_STORED_CHARS) return;
      localStorage.setItem(STORE_PREFIX + key, raw);
      const index = JSON.parse(localStorage.getItem(STORE_PREFIX + 'index') ?? '[]') as string[];
      const next = [...index.filter((k) => k !== key), key];
      for (const old of next.splice(0, Math.max(0, next.length - MAX_ENTRIES))) localStorage.removeItem(STORE_PREFIX + old);
      localStorage.setItem(STORE_PREFIX + 'index', JSON.stringify(next));
    } catch {
      // storage full or blocked (private window): the memory cache still works
    }
  }
}

export const httpCacheInterceptor: HttpInterceptorFn = (req, next) => {
  if (req.method !== 'GET') return next(req);
  const key = req.urlWithParams;
  const slug = cacheSlug(key);
  if (!slug) return next(req);
  const cache = inject(HttpCacheService);
  const kept = cache.get(key);
  if (kept && cache.isFresh(kept)) return of(new HttpResponse({ status: 200, body: kept.body, url: key }));

  const ask = kept?.etag ? req.clone({ setHeaders: { 'If-None-Match': kept.etag } }) : req;
  return next(ask).pipe(
    tap((ev) => {
      if (ev instanceof HttpResponse && ev.status === 200) cache.put(key, slug, ev.headers.get('ETag'), ev.body);
    }),
    catchError((err: { status?: number }) => {
      if (err?.status === 304 && kept) {
        cache.confirm(key);
        return of(new HttpResponse({ status: 200, body: kept.body, url: key }));
      }
      return throwError(() => err);
    }),
  );
};
