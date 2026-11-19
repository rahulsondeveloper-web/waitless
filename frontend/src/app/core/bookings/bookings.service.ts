import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';
import { Seated } from '../restaurant/operations.service';

/** Queue & reservations (PRD §12): public, guest ("me") and staff endpoints. */

export type ReservationType = 'free' | 'paid';
export type ReservationStatus =
  | 'pending_payment'
  | 'confirmed'
  | 'checked_in'
  | 'completed'
  | 'cancelled'
  | 'expired'
  | 'no_show';
export type QueueStatus = 'waiting' | 'notified' | 'seated' | 'cancelled' | 'no_show' | 'skipped';

export interface BookingPolicy {
  branch_id: string;
  accepts_reservations: boolean;
  accepts_queue: boolean;
  free_enabled: boolean;
  paid_enabled: boolean;
  booking_fee: string;
  slot_minutes: 15 | 30 | 60;
  dining_minutes: number;
  grace_minutes: number;
  min_lead_minutes: number;
  max_advance_days: number;
  min_party: number;
  max_party: number;
  free_cancel_hours: number;
  refund_on_no_show: boolean;
}

export interface BookingOptions {
  branch_id: string;
  branch_name: string;
  accepts_reservations: boolean;
  accepts_queue: boolean;
  free_enabled: boolean;
  paid_enabled: boolean;
  booking_fee: string;
  currency: string;
  min_party: number;
  max_party: number;
  max_advance_days: number;
  grace_minutes: number;
  free_cancel_hours: number;
}

export interface Slot {
  starts_at: string;
  label: string;
  available: boolean;
}

export interface Availability {
  branch_id: string;
  date: string;
  timezone: string;
  party_size: number;
  slots: Slot[];
  free_enabled: boolean;
  paid_enabled: boolean;
  booking_fee: string;
  currency: string;
  grace_minutes: number;
  free_cancel_hours: number;
  message: string | null;
}

export interface Checkout {
  provider: string;
  order_id: string;
  amount: string;
  currency: string;
  checkout: { url?: string; key_id?: string; order_id?: string; amount?: number; currency?: string };
}

export interface Reservation {
  id: string;
  code: string;
  branch_id: string;
  branch_name: string | null;
  restaurant_name: string | null;
  restaurant_slug: string | null;
  guest_name: string;
  phone: string | null;
  party_size: number;
  type: ReservationType;
  status: ReservationStatus;
  starts_at: string;
  ends_at: string;
  arrival_deadline: string;
  payment_due_at: string | null;
  booking_fee: string;
  notes: string;
  table_labels: string[];
  staff_confirmed_at: string | null;
  ended_at: string | null;
  end_reason: string | null;
  payment_status: string | null;
  refunded_amount: string | null;
  can_cancel: boolean;
  can_preorder: boolean;
}

export interface BookingResult {
  reservation: Reservation;
  payment: Checkout | null;
}

export interface QueueEntry {
  id: string;
  branch_id: string;
  token: string;
  party_size: number;
  guest_name: string;
  phone: string | null;
  source: 'online' | 'staff';
  status: QueueStatus;
  position: number;
  ahead: number;
  estimated_wait_minutes: number | null;
  joined_at: string;
  notified_at: string | null;
  ended_at: string | null;
  notified_table_label: string | null;
  restaurant_name: string | null;
  restaurant_slug: string | null;
  /** Only on the join response when a free table suited the party: the guest is seated right away. */
  seated_now?: SeatedNow | null;
}

export interface SeatedNow {
  table_label: string;
  capacity: number;
  /** guests beyond the table's seats — the waiter brings chairs */
  extra_chairs: number;
  code: string;
  pin: string;
  token: string;
  expires_at: string;
  session_id: string;
}

export interface WaitTime {
  branch_id: string;
  accepting: boolean;
  waiting: number;
  estimated_wait_minutes: number | null;
  free_tables: number;
}

export interface MyBookings {
  reservations: Reservation[];
  queue: QueueEntry[];
}

export interface MockOrder {
  order_id: string;
  amount: string;
  currency: string;
  status: string;
  reservation_id: string;
  reservation_code: string;
  restaurant_name: string;
  restaurant_slug: string;
}

export const RESERVATION_STATUS_LABEL: Record<ReservationStatus, string> = {
  pending_payment: 'Awaiting payment',
  confirmed: 'Confirmed',
  checked_in: 'Arrived',
  completed: 'Completed',
  cancelled: 'Cancelled',
  expired: 'Expired',
  no_show: 'No-show',
};

export const QUEUE_STATUS_LABEL: Record<QueueStatus, string> = {
  waiting: 'Waiting',
  notified: 'Table ready',
  seated: 'Seated',
  cancelled: 'Cancelled',
  no_show: 'No-show',
  skipped: 'Skipped',
};

@Injectable({ providedIn: 'root' })
export class BookingsService {
  private readonly api = inject(ApiService);

  // ---------- public ----------
  options(slug: string): Observable<BookingOptions[]> {
    return this.api.get(`public/restaurants/${encodeURIComponent(slug)}/booking-options`);
  }
  availability(slug: string, branchId: string, date: string, party: number): Observable<Availability> {
    return this.api.get(`public/restaurants/${encodeURIComponent(slug)}/availability`, {
      branch_id: branchId,
      date,
      party,
    });
  }
  waitTime(slug: string, branchId: string, party = 2): Observable<WaitTime> {
    return this.api.get(`public/restaurants/${encodeURIComponent(slug)}/wait-time`, { branch_id: branchId, party });
  }

  // ---------- guest ----------
  /** `seat_now`: seat the guest at once when a free table suits the party (else a normal token). */
  joinQueue(
    slug: string,
    body: { branch_id: string; party_size: number; guest_name?: string; seat_now?: boolean },
  ): Observable<QueueEntry> {
    return this.api.post(`public/restaurants/${encodeURIComponent(slug)}/queue`, body);
  }
  book(
    slug: string,
    body: { branch_id: string; starts_at: string; party_size: number; type: ReservationType; guest_name?: string; notes?: string },
  ): Observable<BookingResult> {
    return this.api.post(`public/restaurants/${encodeURIComponent(slug)}/reservations`, body);
  }
  myBookings(): Observable<MyBookings> {
    return this.api.get('me/bookings');
  }
  myQueueEntry(id: string): Observable<QueueEntry> {
    return this.api.get(`me/queue/${id}`);
  }
  leaveQueue(id: string): Observable<QueueEntry> {
    return this.api.post(`me/queue/${id}/leave`, {});
  }
  myReservation(id: string): Observable<Reservation> {
    return this.api.get(`me/reservations/${id}`);
  }
  cancelMine(id: string): Observable<Reservation> {
    return this.api.post(`me/reservations/${id}/cancel`, {});
  }
  retryPayment(id: string): Observable<Checkout> {
    return this.api.post(`me/reservations/${id}/pay`, {});
  }
  mockOrder(orderId: string): Observable<MockOrder> {
    return this.api.get(`public/payments/mock/${encodeURIComponent(orderId)}`);
  }
  mockPay(orderId: string, success: boolean): Observable<{ result: string }> {
    return this.api.post(`public/payments/mock/${encodeURIComponent(orderId)}`, { success });
  }

  // ---------- staff ----------
  queue(branchId: string, history = false): Observable<QueueEntry[]> {
    return this.api.get('restaurant/queue', { branch_id: branchId, history });
  }
  addToQueue(body: { branch_id: string; party_size: number; guest_name: string; phone?: string | null }): Observable<QueueEntry> {
    return this.api.post('restaurant/queue', body);
  }
  notifyQueue(id: string, tableId: string | null): Observable<QueueEntry> {
    return this.api.post(`restaurant/queue/${id}/notify`, { table_id: tableId });
  }
  seatQueue(id: string, tableId: string): Observable<Seated> {
    return this.api.post(`restaurant/queue/${id}/seat`, { table_id: tableId });
  }
  moveQueue(id: string, direction: 'up' | 'down'): Observable<QueueEntry[]> {
    return this.api.post(`restaurant/queue/${id}/move`, { direction });
  }
  endQueue(id: string, action: 'skip' | 'no-show' | 'cancel'): Observable<QueueEntry> {
    return this.api.post(`restaurant/queue/${id}/${action}`, {});
  }
  reservations(branchId: string, date?: string): Observable<Reservation[]> {
    return this.api.get('restaurant/reservations', { branch_id: branchId, date });
  }
  staffAvailability(branchId: string, date: string, party: number): Observable<Availability> {
    return this.api.get('restaurant/reservations/availability', { branch_id: branchId, date, party });
  }
  staffBook(body: {
    branch_id: string;
    starts_at: string;
    party_size: number;
    guest_name: string;
    phone?: string | null;
    notes?: string;
  }): Observable<BookingResult> {
    return this.api.post('restaurant/reservations', body);
  }
  arrive(id: string, tableId: string | null = null): Observable<Seated> {
    return this.api.post(`restaurant/reservations/${id}/arrive`, { table_id: tableId });
  }
  staffCancel(id: string): Observable<Reservation> {
    return this.api.post(`restaurant/reservations/${id}/cancel`, {});
  }
  noShow(id: string): Observable<Reservation> {
    return this.api.post(`restaurant/reservations/${id}/no-show`, {});
  }
  policy(branchId: string): Observable<BookingPolicy> {
    return this.api.get(`restaurant/branches/${branchId}/booking-policy`);
  }
  savePolicy(branchId: string, body: Omit<BookingPolicy, 'branch_id'>): Observable<BookingPolicy> {
    return this.api.put(`restaurant/branches/${branchId}/booking-policy`, body);
  }
}

/** "2026-11-18" in the given IANA time zone. */
export function localDate(tz: string, d = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
}

/** "Wed 18 Nov, 19:30" in the given time zone. */
export function formatWhen(iso: string, tz = 'Asia/Kolkata'): string {
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: tz,
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(iso));
}
