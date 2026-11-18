import { HttpClient, HttpHeaders, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';

import { HttpCacheService, cacheSlug, httpCacheInterceptor } from './http-cache.service';

const MENU = '/api/v1/public/restaurants/urban-bites/menu?limit=10';

describe('httpCacheInterceptor', () => {
  let http: HttpClient;
  let ctl: HttpTestingController;
  let cache: HttpCacheService;

  beforeEach(() => {
    try {
      localStorage.clear();
    } catch {
      /* no storage */
    }
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([httpCacheInterceptor])), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpClient);
    ctl = TestBed.inject(HttpTestingController);
    cache = TestBed.inject(HttpCacheService);
  });

  afterEach(() => ctl.verify());

  async function get(url = MENU): Promise<unknown> {
    return firstValueFrom(http.get(url));
  }

  it('calls the API once, then serves the kept response', async () => {
    const first = get();
    ctl.expectOne(MENU).flush({ v: 1 }, { headers: new HttpHeaders({ ETag: 'W/"a"' }) });
    expect(await first).toEqual({ v: 1 });
    expect(await get()).toEqual({ v: 1 }); // no request: ctl.verify() would fail otherwise
  });

  it('after a change push asks again with the ETag: 304 keeps the copy, 200 replaces it', async () => {
    const first = get();
    ctl.expectOne(MENU).flush({ v: 1 }, { headers: new HttpHeaders({ ETag: 'W/"a"' }) });
    await first;

    cache.invalidate('urban-bites');
    const same = get();
    const ask = ctl.expectOne(MENU);
    expect(ask.request.headers.get('If-None-Match')).toBe('W/"a"');
    ask.flush(null, { status: 304, statusText: 'Not Modified' });
    expect(await same).toEqual({ v: 1 });
    expect(await get()).toEqual({ v: 1 }); // confirmed: served from the cache again

    cache.invalidate('urban-bites');
    const changed = get();
    ctl.expectOne(MENU).flush({ v: 2 }, { headers: new HttpHeaders({ ETag: 'W/"b"' }) });
    expect(await changed).toEqual({ v: 2 });
    expect(await get()).toEqual({ v: 2 });
  });

  it("a change at one restaurant leaves another restaurant's copy alone", async () => {
    const other = '/api/v1/public/restaurants/remelle/gallery';
    const a = get();
    ctl.expectOne(MENU).flush({ v: 1 }, { headers: new HttpHeaders({ ETag: 'W/"a"' }) });
    const b = get(other);
    ctl.expectOne(other).flush({ g: 1 }, { headers: new HttpHeaders({ ETag: 'W/"g"' }) });
    await Promise.all([a, b]);
    cache.invalidate('urban-bites');
    expect(await get(other)).toEqual({ g: 1 });
    const again = get();
    ctl.expectOne(MENU).flush(null, { status: 304, statusText: 'Not Modified' });
    await again;
  });

  it('revalidates everything after a reconnect (a push may have been missed)', async () => {
    const first = get();
    ctl.expectOne(MENU).flush({ v: 1 }, { headers: new HttpHeaders({ ETag: 'W/"a"' }) });
    await first;
    cache.markAllStale();
    const again = get();
    ctl.expectOne(MENU).flush(null, { status: 304, statusText: 'Not Modified' });
    expect(await again).toEqual({ v: 1 });
  });

  it('never caches personal or live endpoints', async () => {
    for (const url of [
      '/api/v1/public/restaurants/urban-bites/availability?date=2026-11-18',
      '/api/v1/public/restaurants/urban-bites/tables/abcdefgh12',
      '/api/v1/table-session/bills',
      '/api/v1/me/orders',
    ]) {
      expect(cacheSlug(url)).toBeNull();
      const r = get(url);
      ctl.expectOne(url).flush({ ok: 1 });
      await r;
      const r2 = get(url);
      ctl.expectOne(url).flush({ ok: 2 }); // asked again every time
      expect(await r2).toEqual({ ok: 2 });
    }
  });

  it('recognises the storefront reads', () => {
    expect(cacheSlug('/api/v1/public/restaurants/urban-bites')).toBe('urban-bites');
    expect(cacheSlug('/api/v1/public/restaurants/urban-bites/branding')).toBe('urban-bites');
    expect(
      cacheSlug('/api/v1/public/restaurants/urban-bites/menu/categories/0b1c2d3e-0000-4000-8000-000000000000/items?offset=10'),
    ).toBe('urban-bites');
  });
});

describe('HttpCacheService change counters', () => {
  it('a reply to a request sent before a push is stale, even in the same millisecond', () => {
    const cache = new HttpCacheService();
    const before = cache.stamp('urban-bites');
    cache.invalidate('urban-bites'); // the push arrives while the request is in flight
    cache.put('k', 'urban-bites', 'W/"a"', { v: 1 }, before);
    expect(cache.isFresh(cache.get('k')!)).toBe(false);
    cache.put('k', 'urban-bites', 'W/"a"', { v: 1 }, cache.stamp('urban-bites'));
    expect(cache.isFresh(cache.get('k')!)).toBe(true);
  });
});
