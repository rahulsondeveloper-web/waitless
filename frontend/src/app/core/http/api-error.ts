import { HttpErrorResponse } from '@angular/common/http';

/** Mirrors the backend error envelope: { error: { code, message, details } }. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = 'ApiError';
  }

  static from(err: unknown): ApiError {
    if (err instanceof ApiError) return err;
    if (err instanceof HttpErrorResponse) {
      const body = err.error?.error;
      if (body && typeof body.code === 'string') {
        return new ApiError(err.status, body.code, body.message ?? 'Request failed.', body.details ?? {});
      }
      if (err.status === 0) {
        return new ApiError(0, 'NETWORK_ERROR', 'Cannot reach the server. Check your connection.');
      }
      return new ApiError(err.status, 'HTTP_ERROR', err.message);
    }
    return new ApiError(0, 'UNKNOWN_ERROR', err instanceof Error ? err.message : 'Unexpected error.');
  }
}
