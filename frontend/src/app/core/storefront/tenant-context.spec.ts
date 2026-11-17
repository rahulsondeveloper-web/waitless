import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { storefront } from '../../testing/fixtures';
import { formatPrice } from './storefront.models';
import { TenantContextService } from './tenant-context.service';

describe('TenantContextService', () => {
  let ctx: TenantContextService;
  let ctrl: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()] });
    ctx = TestBed.inject(TenantContextService);
    ctrl = TestBed.inject(HttpTestingController);
  });

  afterEach(() => ctrl.verify());

  it('drops a late response for a restaurant the guest already left', () => {
    ctx.enter('alpha');
    const alpha = ctrl.expectOne('/api/v1/public/restaurants/alpha');
    ctx.enter('beta');
    expect(alpha.cancelled).toBe(true); // in-flight request cancelled
    ctrl.expectOne('/api/v1/public/restaurants/beta').flush(storefront('beta', 'Beta', null));
    expect(ctx.restaurant()?.name).toBe('Beta');
  });

  it('menu cache is per restaurant', () => {
    ctx.enter('alpha');
    ctrl.expectOne('/api/v1/public/restaurants/alpha').flush(storefront('alpha', 'Alpha', null));
    let alphaMenu: unknown;
    ctx.menu().subscribe((m) => (alphaMenu = m));
    ctrl.expectOne('/api/v1/public/restaurants/alpha/menu').flush({ currency: 'INR', meal_types: [], categories: [{ id: 'a' }] });
    expect(alphaMenu).toBeTruthy();
    ctx.menu().subscribe(); // cached: no second request
    ctx.enter('beta');
    ctrl.expectOne('/api/v1/public/restaurants/beta').flush(storefront('beta', 'Beta', null));
    ctx.menu().subscribe();
    ctrl.expectOne('/api/v1/public/restaurants/beta/menu').flush({ currency: 'INR', meal_types: [], categories: [] });
  });

  it('leave() clears everything', () => {
    ctx.enter('alpha');
    ctrl.expectOne('/api/v1/public/restaurants/alpha').flush(storefront('alpha', 'Alpha', '#123456'));
    ctx.leave();
    expect(ctx.restaurant()).toBeNull();
    expect(ctx.status()).toBe('idle');
  });
});

describe('formatPrice', () => {
  it('formats rupees Indian style', () => {
    expect(formatPrice('520')).toBe('₹520');
    expect(formatPrice('1815.5')).toBe('₹1,815.50');
    expect(formatPrice(150000)).toBe('₹1,50,000');
  });
});
