import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';

/** Call the waiter, restaurant Wi-Fi and reviews (guests with a table token; staff for clearing). */

export type CallKind = 'water' | 'tissue' | 'bill' | 'help';

export const CALL_OPTIONS: { kind: CallKind; label: string; icon: string }[] = [
  { kind: 'water', label: 'Water', icon: 'water_drop' },
  { kind: 'tissue', label: 'Tissue paper', icon: 'layers' },
  { kind: 'bill', label: 'Bill', icon: 'receipt_long' },
  { kind: 'help', label: 'Help', icon: 'support_agent' },
];

export interface ServiceCall {
  id: string;
  branch_id: string;
  table_session_id: string;
  kind: CallKind;
  label: string;
  table_labels: string;
  guest_name: string | null;
  status: 'open' | 'done';
  created_at: string;
  done_at: string | null;
}

export interface CallState {
  can_call: boolean;
  cooldown_until: string | null;
  open: ServiceCall[];
  server_time: string;
}

export interface GuestWifi {
  name: string;
  password: string;
}

export interface Review {
  id: string;
  rating: number;
  comment: string;
  guest_name: string;
  created_at: string;
  hidden?: boolean;
}

export interface ReviewSummary {
  count: number;
  average: number | null;
  reviews: Review[];
}

@Injectable({ providedIn: 'root' })
export class GuestServiceApi {
  private readonly api = inject(ApiService);

  private t(token: string): Record<string, string> {
    return { 'X-Table-Token': token };
  }

  // ---------- guests ----------
  calls(token: string): Observable<CallState> {
    return this.api.getWithHeaders('table-session/calls', this.t(token));
  }
  call(token: string, kind: CallKind, guestName: string): Observable<{ request: ServiceCall; cooldown_until: string; server_time: string }> {
    return this.api.post('table-session/calls', { kind, guest_name: guestName }, this.t(token));
  }
  wifi(token: string): Observable<GuestWifi | null> {
    return this.api.getWithHeaders('table-session/wifi', this.t(token));
  }
  myReview(token: string): Observable<{ can_review: boolean; review: Review | null }> {
    return this.api.getWithHeaders('table-session/review', this.t(token));
  }
  review(token: string, rating: number, comment: string, guestName: string): Observable<Review> {
    return this.api.post('table-session/review', { rating, comment, guest_name: guestName }, this.t(token));
  }
  publicReviews(slug: string): Observable<ReviewSummary> {
    return this.api.get(`public/restaurants/${encodeURIComponent(slug)}/reviews`);
  }

  // ---------- staff ----------
  openCalls(branchId: string): Observable<ServiceCall[]> {
    return this.api.get('restaurant/service-calls', { branch_id: branchId });
  }
  done(id: string): Observable<ServiceCall> {
    return this.api.post(`restaurant/service-calls/${id}/done`, {});
  }
  getWifi(): Observable<GuestWifi> {
    return this.api.get('restaurant/guest-wifi');
  }
  setWifi(w: GuestWifi): Observable<GuestWifi> {
    return this.api.put('restaurant/guest-wifi', w);
  }
  staffReviews(): Observable<ReviewSummary> {
    return this.api.get('restaurant/reviews');
  }
  setHidden(id: string, hidden: boolean): Observable<Review> {
    return this.api.patch(`restaurant/reviews/${id}`, { hidden });
  }
}
