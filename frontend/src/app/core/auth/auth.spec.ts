import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree, provideRouter } from '@angular/router';

import { authGuard, guestGuard, staffGuard, superAdminGuard } from './auth.guards';
import { authInterceptor } from './auth.interceptor';
import { AuthResponse, Me } from './auth.models';
import { AuthService } from './auth.service';

const owner: Me = {
  user: { id: 'u1', full_name: 'Asha Owner', email: 'asha@example.com', phone: '+919876543210', is_super_admin: false },
  memberships: [
    { tenant_id: 't1', tenant_name: 'Urban Bites', tenant_slug: 'urban-bites', tenant_status: 'pending', role_key: 'owner', role_name: 'Owner' },
  ],
  active_tenant: {
    tenant_id: 't1',
    tenant_name: 'Urban Bites',
    tenant_slug: 'urban-bites',
    tenant_status: 'pending',
    role_key: 'owner',
    role_name: 'Owner',
    permissions: { 'menu.manage': 'all' },
    all_branches: true,
    branch_ids: [],
    features: { inventory: { enabled: true, limit: null } },
    subscription: null,
  },
};

const authResponse = (me: Me, token = 'access-1'): AuthResponse => ({
  access_token: token,
  token_type: 'bearer',
  expires_at: new Date(Date.now() + 900_000).toISOString(),
  me,
});

describe('AuthService + interceptor', () => {
  let auth: AuthService;
  let http: HttpClient;
  let ctrl: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    auth = TestBed.inject(AuthService);
    http = TestBed.inject(HttpClient);
    ctrl = TestBed.inject(HttpTestingController);
  });

  afterEach(() => ctrl.verify());

  it('login stores the session and exposes role helpers', () => {
    auth.login('asha@example.com', 'secret').subscribe();
    ctrl.expectOne('/api/v1/auth/login').flush(authResponse(owner));
    expect(auth.isAuthenticated()).toBe(true);
    expect(auth.activeTenant()?.tenant_slug).toBe('urban-bites');
    expect(auth.hasPermission('menu.manage')).toBe(true);
    expect(auth.hasPermission('staff.manage')).toBe(false);
    expect(auth.hasFeature('inventory')).toBe(true);
    expect(auth.homeUrl()).toBe('/restaurant-admin');
  });

  it('adds the bearer token to API calls only', () => {
    auth.login('x', 'y').subscribe();
    ctrl.expectOne('/api/v1/auth/login').flush(authResponse(owner));

    http.get('/api/v1/restaurant/me').subscribe();
    expect(ctrl.expectOne('/api/v1/restaurant/me').request.headers.get('Authorization')).toBe('Bearer access-1');

    http.get('https://tiles.example.com/1.png').subscribe();
    expect(ctrl.expectOne('https://tiles.example.com/1.png').request.headers.has('Authorization')).toBe(false);
  });

  it('on 401 refreshes once and retries with the new token', () => {
    auth.login('x', 'y').subscribe();
    ctrl.expectOne('/api/v1/auth/login').flush(authResponse(owner));

    let body: unknown;
    http.get('/api/v1/restaurant/me').subscribe((b) => (body = b));
    ctrl.expectOne('/api/v1/restaurant/me').flush({ error: { code: 'TOKEN_EXPIRED' } }, { status: 401, statusText: 'x' });
    ctrl.expectOne('/api/v1/auth/refresh').flush(authResponse(owner, 'access-2'));
    const retry = ctrl.expectOne('/api/v1/restaurant/me');
    expect(retry.request.headers.get('Authorization')).toBe('Bearer access-2');
    retry.flush({ ok: true });
    expect(body).toEqual({ ok: true });
  });

  it('clears the session when the refresh also fails', () => {
    auth.login('x', 'y').subscribe();
    ctrl.expectOne('/api/v1/auth/login').flush(authResponse(owner));

    let failed = false;
    http.get('/api/v1/restaurant/me').subscribe({ error: () => (failed = true) });
    ctrl.expectOne('/api/v1/restaurant/me').flush({}, { status: 401, statusText: 'x' });
    ctrl.expectOne('/api/v1/auth/refresh').flush({ error: { code: 'REFRESH_TOKEN_REUSED' } }, { status: 401, statusText: 'x' });
    expect(failed).toBe(true);
    expect(auth.isAuthenticated()).toBe(false);
  });

  it('does not loop on a failing login', () => {
    let code = '';
    auth.login('x', 'bad').subscribe({ error: (e) => (code = e.code) });
    ctrl
      .expectOne('/api/v1/auth/login')
      .flush({ error: { code: 'INVALID_CREDENTIALS', message: 'Invalid' } }, { status: 401, statusText: 'x' });
    ctrl.expectNone('/api/v1/auth/refresh');
    expect(code).toBe('INVALID_CREDENTIALS');
  });

  it('restore() resolves quietly when there is no session', async () => {
    const done = auth.restore();
    ctrl.expectOne('/api/v1/auth/refresh').flush({ error: { code: 'NO_REFRESH_TOKEN' } }, { status: 401, statusText: 'x' });
    await done;
    expect(auth.isAuthenticated()).toBe(false);
  });
});

describe('route guards', () => {
  let auth: AuthService;
  let ctrl: HttpTestingController;
  const route = {} as ActivatedRouteSnapshot;
  const state = { url: '/restaurant-admin' } as RouterStateSnapshot;
  const run = (guard: typeof authGuard) => TestBed.runInInjectionContext(() => guard(route, state));
  const url = (r: unknown) => (r instanceof UrlTree ? TestBed.inject(Router).serializeUrl(r) : r);

  const signIn = (me: Me) => {
    auth.login('x', 'y').subscribe();
    ctrl.expectOne('/api/v1/auth/login').flush(authResponse(me));
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(withInterceptors([authInterceptor])), provideHttpClientTesting()],
    });
    auth = TestBed.inject(AuthService);
    ctrl = TestBed.inject(HttpTestingController);
  });

  it('anonymous users are sent to login with a return URL', () => {
    expect(url(run(authGuard))).toBe('/login?returnUrl=%2Frestaurant-admin');
    expect(url(run(staffGuard))).toBe('/login?returnUrl=%2Frestaurant-admin');
    expect(run(guestGuard)).toBe(true);
  });

  it('restaurant staff may enter restaurant admin but not super admin', () => {
    signIn(owner);
    expect(run(staffGuard)).toBe(true);
    expect(url(run(superAdminGuard))).toBe('/restaurant-admin');
    expect(url(run(guestGuard))).toBe('/restaurant-admin');
  });

  it('a customer without a restaurant cannot enter restaurant admin', () => {
    signIn({ ...owner, memberships: [], active_tenant: null });
    expect(url(run(staffGuard))).toBe('/customer');
  });

  it('super admin may enter super admin', () => {
    signIn({ user: { ...owner.user, is_super_admin: true }, memberships: [], active_tenant: null });
    expect(run(superAdminGuard)).toBe(true);
  });
});
