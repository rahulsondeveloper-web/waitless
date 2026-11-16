import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';

/** Signed in (any role). Otherwise → /login?returnUrl=… */
export const authGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  return auth.isAuthenticated() || inject(Router).createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
};

/** Staff of a restaurant with an active tenant selected. */
export const staffGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (!auth.isAuthenticated()) return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
  return auth.activeTenant() !== null || router.createUrlTree([auth.homeUrl()]);
};

/** WaitLess platform owner only. */
export const superAdminGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (!auth.isAuthenticated()) return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
  return auth.isSuperAdmin() || router.createUrlTree([auth.homeUrl()]);
};

/** Login/register pages: signed-in users go to their home instead. */
export const guestGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return !auth.isAuthenticated() || inject(Router).createUrlTree([auth.homeUrl()]);
};
