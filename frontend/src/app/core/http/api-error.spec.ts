import { HttpErrorResponse } from '@angular/common/http';

import { ApiError } from './api-error';

describe('ApiError.from', () => {
  it('reads the backend error envelope', () => {
    const e = ApiError.from(
      new HttpErrorResponse({
        status: 409,
        error: { error: { code: 'TABLE_ALREADY_ASSIGNED', message: 'Taken', details: { table: 'T5' } } },
      }),
    );
    expect(e.status).toBe(409);
    expect(e.code).toBe('TABLE_ALREADY_ASSIGNED');
    expect(e.message).toBe('Taken');
    expect(e.details).toEqual({ table: 'T5' });
  });

  it('reports network failures clearly', () => {
    const e = ApiError.from(new HttpErrorResponse({ status: 0 }));
    expect(e.code).toBe('NETWORK_ERROR');
  });

  it('wraps unknown errors', () => {
    expect(ApiError.from(new Error('x')).code).toBe('UNKNOWN_ERROR');
  });
});
