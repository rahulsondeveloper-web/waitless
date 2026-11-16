import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';
import { routes } from './app.routes';

describe('App', () => {
  it('creates the root component', async () => {
    await TestBed.configureTestingModule({ imports: [App], providers: [provideRouter(routes)] }).compileComponents();
    expect(TestBed.createComponent(App).componentInstance).toBeTruthy();
  });

  it('declares every route area from PRD §19', () => {
    const top = routes.map((r) => r.path);
    expect(top).toEqual(expect.arrayContaining(['', 'r/:slug', 'restaurant-admin', 'super-admin', '**']));
    const platformChildren = routes.find((r) => r.path === '')?.children?.map((c) => c.path);
    expect(platformChildren).toEqual(expect.arrayContaining(['', 'about', 'restaurants', 'customer']));
    const storefrontChildren = routes.find((r) => r.path === 'r/:slug')?.children?.map((c) => c.path);
    expect(storefrontChildren).toEqual(
      expect.arrayContaining(['', 'menu', 'gallery', 'about', 'reservations', 'contact']),
    );
  });
});
