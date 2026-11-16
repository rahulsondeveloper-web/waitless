import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, finalize, firstValueFrom, map, of, shareReplay, tap } from 'rxjs';

import { APP_CONFIG } from '../config/app-config';
import { ApiError } from '../http/api-error';
import { AuthResponse, Me, OtpSendResponse } from './auth.models';

/**
 * Session state. The access token lives only in memory; the refresh token is an HttpOnly cookie
 * the browser sends to /api/v1/auth/* (never readable by JavaScript).
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly base = `${APP_CONFIG.apiBase}/auth`;

  private readonly _token = signal<string | null>(null);
  private readonly _me = signal<Me | null>(null);
  private refreshInFlight$: Observable<AuthResponse> | null = null;

  readonly me = this._me.asReadonly();
  readonly isAuthenticated = computed(() => this._me() !== null);
  readonly user = computed(() => this._me()?.user ?? null);
  readonly isSuperAdmin = computed(() => this._me()?.user.is_super_admin ?? false);
  readonly activeTenant = computed(() => this._me()?.active_tenant ?? null);
  readonly memberships = computed(() => this._me()?.memberships ?? []);

  token(): string | null {
    return this._token();
  }

  hasPermission(permission: string): boolean {
    return !!this.activeTenant()?.permissions[permission];
  }

  hasFeature(feature: string): boolean {
    return !!this.activeTenant()?.features[feature]?.enabled;
  }

  login(identifier: string, password: string): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.base}/login`, { identifier, password })
      .pipe(tap((r) => this.apply(r)), catchError(rethrow));
  }

  sendOtp(phone: string): Observable<OtpSendResponse> {
    return this.http.post<OtpSendResponse>(`${this.base}/otp/send`, { phone }).pipe(catchError(rethrow));
  }

  verifyOtp(phone: string, code: string, fullName?: string): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.base}/otp/verify`, { phone, code, full_name: fullName || null })
      .pipe(tap((r) => this.apply(r)), catchError(rethrow));
  }

  /** One refresh at a time; concurrent 401s share it. */
  refresh(): Observable<AuthResponse> {
    if (!this.refreshInFlight$) {
      this.refreshInFlight$ = this.http.post<AuthResponse>(`${this.base}/refresh`, {}).pipe(
        tap((r) => this.apply(r)),
        catchError(rethrow),
        finalize(() => (this.refreshInFlight$ = null)),
        shareReplay(1),
      );
    }
    return this.refreshInFlight$;
  }

  /** Called once at startup: silently restores the session from the refresh cookie, if any. */
  restore(): Promise<void> {
    return firstValueFrom(
      this.refresh().pipe(
        map(() => undefined),
        catchError(() => {
          this.clearSession();
          return of(undefined);
        }),
      ),
    );
  }

  switchTenant(tenantId: string | null): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.base}/switch-tenant`, { tenant_id: tenantId })
      .pipe(tap((r) => this.apply(r)), catchError(rethrow));
  }

  changePassword(currentPassword: string, newPassword: string): Observable<void> {
    return this.http
      .post<void>(`${this.base}/password/change`, { current_password: currentPassword, new_password: newPassword })
      .pipe(catchError(rethrow));
  }

  logout(): void {
    this.http
      .post(`${this.base}/logout`, {})
      .pipe(catchError(() => of(null)))
      .subscribe(() => {
        this.clearSession();
        void this.router.navigateByUrl('/');
      });
  }

  clearSession(): void {
    this._token.set(null);
    this._me.set(null);
  }

  /** Where a user lands after signing in. */
  homeUrl(): string {
    if (this.isSuperAdmin()) return '/super-admin/restaurants';
    if (this.activeTenant()) return '/restaurant-admin';
    return '/customer';
  }

  private apply(res: AuthResponse): void {
    this._token.set(res.access_token);
    this._me.set(res.me);
  }
}

function rethrow(err: unknown): Observable<never> {
  throw ApiError.from(err);
}
