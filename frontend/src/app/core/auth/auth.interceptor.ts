import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';

import { APP_CONFIG } from '../config/app-config';
import { AuthService } from './auth.service';

/** Endpoints that must never trigger a refresh-and-retry loop. */
const NO_RETRY = /\/auth\/(login|refresh|otp\/|logout)/;

/**
 * Adds the access token to API calls. On 401 it refreshes once (cookie) and retries the request;
 * if refreshing fails the session is cleared and the original error is returned.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith(APP_CONFIG.apiBase)) return next(req);
  const auth = inject(AuthService);

  const withToken = (r: HttpRequest<unknown>) => {
    const token = auth.token();
    return token ? r.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : r;
  };

  return next(withToken(req)).pipe(
    catchError((err: unknown) => {
      const canRetry =
        err instanceof HttpErrorResponse && err.status === 401 && !NO_RETRY.test(req.url) && auth.token() !== null;
      if (!canRetry) return throwError(() => err);
      return auth.refresh().pipe(
        catchError(() => {
          auth.clearSession();
          return throwError(() => err);
        }),
        switchMap(() => next(withToken(req))),
      );
    }),
  );
};
