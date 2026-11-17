import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { BookingsService, formatWhen, localDate } from './bookings.service';

describe('booking helpers', () => {
  it('gives the calendar date in the branch time zone, not the browser one', () => {
    // 20:00 UTC on 17 Nov is already 18 Nov in India (UTC+5:30).
    const at = new Date('2026-11-17T20:00:00Z');
    expect(localDate('Asia/Kolkata', at)).toBe('2026-11-18');
    expect(localDate('UTC', at)).toBe('2026-11-17');
  });

  it('formats a booking time in the branch time zone', () => {
    const text = formatWhen('2026-11-18T14:00:00Z', 'Asia/Kolkata');
    expect(text).toContain('19:30');
    expect(text).toContain('18');
  });
});

describe('BookingsService', () => {
  let api: BookingsService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(BookingsService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('asks for availability of one branch, date and party size', () => {
    api.availability('urban-bites', 'b1', '2026-11-18', 4).subscribe();
    const req = http.expectOne((r) => r.url.endsWith('/public/restaurants/urban-bites/availability'));
    expect(req.request.params.get('branch_id')).toBe('b1');
    expect(req.request.params.get('date')).toBe('2026-11-18');
    expect(req.request.params.get('party')).toBe('4');
    req.flush({ slots: [] });
  });

  it('books through the restaurant storefront and never sends a status', () => {
    api
      .book('urban-bites', { branch_id: 'b1', starts_at: '2026-11-18T14:00:00Z', party_size: 2, type: 'paid' })
      .subscribe();
    const req = http.expectOne((r) => r.url.endsWith('/public/restaurants/urban-bites/reservations'));
    expect(req.request.method).toBe('POST');
    expect(req.request.body).not.toHaveProperty('status');
    req.flush({ reservation: {}, payment: null });
  });

  it('uses the staff endpoints for queue actions', () => {
    api.endQueue('e1', 'no-show').subscribe();
    http.expectOne((r) => r.url.endsWith('/restaurant/queue/e1/no-show')).flush({});
    api.notifyQueue('e1', 't9').subscribe();
    const req = http.expectOne((r) => r.url.endsWith('/restaurant/queue/e1/notify'));
    expect(req.request.body).toEqual({ table_id: 't9' });
    req.flush({});
  });
});
