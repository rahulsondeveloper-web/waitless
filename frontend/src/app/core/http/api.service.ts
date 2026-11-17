import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';

import { APP_CONFIG } from '../config/app-config';
import { ApiError } from './api-error';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Thin typed wrapper over HttpClient: prefixes the API base and normalises errors to ApiError. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  get<T>(path: string, params?: Params): Observable<T> {
    return this.http.get<T>(this.url(path), { params: toParams(params) }).pipe(catchError(rethrow));
  }

  getWithHeaders<T>(path: string, headers: Record<string, string>, params?: Params): Observable<T> {
    return this.http.get<T>(this.url(path), { params: toParams(params), headers }).pipe(catchError(rethrow));
  }

  post<T>(path: string, body: unknown, headers?: Record<string, string>): Observable<T> {
    return this.http.post<T>(this.url(path), body, { headers }).pipe(catchError(rethrow));
  }

  put<T>(path: string, body: unknown): Observable<T> {
    return this.http.put<T>(this.url(path), body).pipe(catchError(rethrow));
  }

  patch<T>(path: string, body: unknown): Observable<T> {
    return this.http.patch<T>(this.url(path), body).pipe(catchError(rethrow));
  }

  delete<T>(path: string): Observable<T> {
    return this.http.delete<T>(this.url(path)).pipe(catchError(rethrow));
  }

  private url(path: string): string {
    return `${APP_CONFIG.apiBase}/${path.replace(/^\//, '')}`;
  }
}

function rethrow(err: unknown) {
  return throwError(() => ApiError.from(err));
}

function toParams(params?: Params): HttpParams | undefined {
  if (!params) return undefined;
  let p = new HttpParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') p = p.set(k, String(v));
  }
  return p;
}
