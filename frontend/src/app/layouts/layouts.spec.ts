import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { ThemeService } from '../core/theme/theme.service';
import { DEFAULT_THEME } from '../core/theme/theme.tokens';
import { storefront } from '../testing/fixtures';
import { PlatformLayoutComponent } from './platform-layout/platform-layout.component';
import { StorefrontLayoutComponent } from './storefront-layout/storefront-layout.component';

@Component({ template: 'page' })
class BlankPage {}

describe('layouts', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: '', component: PlatformLayoutComponent, children: [{ path: '', component: BlankPage }] },
          { path: 'r/:slug', component: StorefrontLayoutComponent, children: [{ path: '', component: BlankPage }] },
        ]),
      ],
    });
  });

  it('platform layout shows WaitLess branding and restores the default theme', async () => {
    const theme = TestBed.inject(ThemeService);
    theme.apply({ primary: '#0a7c86' });
    const harness = await RouterTestingHarness.create('/');
    const el = harness.routeNativeElement as HTMLElement;
    expect(el.querySelector('img[alt="WaitLess"]')).toBeTruthy();
    expect(theme.tokens().primary).toBe(DEFAULT_THEME.primary);
    // Signed out → login entry point is visible.
    expect(el.querySelector('wl-user-menu a[href="/login"]')).toBeTruthy();
  });

  it('storefront header shows the restaurant from the API and always keeps the WaitLess link', async () => {
    const ctrl = TestBed.inject(HttpTestingController);
    const harness = await RouterTestingHarness.create('/r/urban-bites');
    ctrl.expectOne('/api/v1/public/restaurants/urban-bites').flush(storefront('urban-bites', 'Urban Bites', '#0a7c86'));
    harness.detectChanges();
    const el = harness.routeNativeElement as HTMLElement;
    expect(el.querySelector('.sf-brand__name')?.textContent?.trim()).toBe('Urban Bites');
    expect(el.querySelector<HTMLAnchorElement>('a.sf-waitless')?.getAttribute('href')).toBe('/');
    expect(TestBed.inject(ThemeService).tokens().primary).toBe('#0a7c86');
  });

  it('switching restaurants replaces name and theme (no stale tenant data)', async () => {
    const ctrl = TestBed.inject(HttpTestingController);
    const harness = await RouterTestingHarness.create('/r/urban-bites');
    ctrl.expectOne('/api/v1/public/restaurants/urban-bites').flush(storefront('urban-bites', 'Urban Bites', '#0a7c86'));
    await harness.navigateByUrl('/r/remelle');
    const el = harness.routeNativeElement as HTMLElement;
    expect(el.querySelector('.sf-brand__name')?.textContent?.trim()).toBe(''); // A cleared before B arrives
    ctrl.expectOne('/api/v1/public/restaurants/remelle').flush(storefront('remelle', 'Restaurant Remelle', null));
    harness.detectChanges();
    expect(el.querySelector('.sf-brand__name')?.textContent?.trim()).toBe('Restaurant Remelle');
    expect(TestBed.inject(ThemeService).tokens().primary).toBe(DEFAULT_THEME.primary);
  });

  it('unknown restaurant shows a friendly not-found message', async () => {
    const ctrl = TestBed.inject(HttpTestingController);
    const harness = await RouterTestingHarness.create('/r/nowhere');
    ctrl
      .expectOne('/api/v1/public/restaurants/nowhere')
      .flush({ error: { code: 'NOT_FOUND', message: 'Restaurant not found.' } }, { status: 404, statusText: 'x' });
    harness.detectChanges();
    expect((harness.routeNativeElement as HTMLElement).textContent).toContain("isn't on WaitLess yet");
  });
});
