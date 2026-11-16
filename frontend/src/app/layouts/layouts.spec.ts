import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { ThemeService } from '../core/theme/theme.service';
import { DEFAULT_THEME } from '../core/theme/theme.tokens';
import { PlatformLayoutComponent } from './platform-layout/platform-layout.component';
import { StorefrontLayoutComponent } from './storefront-layout/storefront-layout.component';

@Component({ template: 'page' })
class BlankPage {}

describe('layouts', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
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
  });

  it('storefront header shows the restaurant and always keeps the WaitLess link', async () => {
    const harness = await RouterTestingHarness.create('/r/urban-bites');
    const el = harness.routeNativeElement as HTMLElement;
    expect(el.querySelector('.sf-brand__name')?.textContent?.trim()).toBe('Urban Bites');
    const waitless = el.querySelector<HTMLAnchorElement>('a.sf-waitless');
    expect(waitless?.getAttribute('href')).toBe('/');
  });

  it('switching restaurants replaces the header name (no stale tenant data)', async () => {
    const harness = await RouterTestingHarness.create('/r/urban-bites');
    await harness.navigateByUrl('/r/tales-and-spirits');
    const el = harness.routeNativeElement as HTMLElement;
    expect(el.querySelector('.sf-brand__name')?.textContent?.trim()).toBe('Tales And Spirits');
  });
});
