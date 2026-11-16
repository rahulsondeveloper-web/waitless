import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, of } from 'rxjs';

import { APP_CONFIG } from '../config/app-config';
import { ApiError } from '../http/api-error';

export interface HealthCheck {
  status: 'ok' | 'down' | 'disabled';
  latency_ms?: number | null;
  detail?: string | null;
}

export interface Health {
  status: 'ok' | 'degraded';
  version: string;
  environment: string;
  server_time: string;
  checks: Record<'database' | 'redis' | 'worker', HealthCheck>;
}

@Injectable({ providedIn: 'root' })
export class HealthService {
  private readonly http = inject(HttpClient);

  /** /health answers 503 with a full body when degraded, so read the body in both cases. */
  check(): Observable<Health> {
    return this.http.get<Health>(`${APP_CONFIG.apiBase}/health`).pipe(
      catchError((err) => {
        if (err?.error?.checks) return of(err.error as Health);
        throw ApiError.from(err);
      }),
    );
  }
}
