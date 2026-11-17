import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';
import { MenuWindow, PublicItem } from '../storefront/storefront.models';
import { ServingPromise, Sla } from './sla';

/** Ordering & kitchen (PRD §13): table code + PIN, guest/staff orders, paid pre-orders. */

export type OrderStatus = 'placed' | 'accepted' | 'preparing' | 'ready' | 'served' | 'cancelled';

export interface OrderLineIn {
  menu_item_id: string;
  variant_id?: string | null;
  addon_ids?: string[];
  quantity: number;
  instructions?: string;
}

export interface OrderLine {
  id: string;
  menu_item_id: string | null;
  name: string;
  variant_name: string | null;
  addons: { name: string; price: string }[];
  food_class: string;
  unit_price: string;
  quantity: number;
  tax_pct: string;
  line_total: string;
  tax_amount: string;
  instructions: string;
}

export interface Order {
  id: string;
  branch_id: string;
  number: string;
  order_type: 'walk_in' | 'booking' | 'staff' | 'paid_preorder';
  source: 'guest' | 'staff';
  status: OrderStatus;
  table_session_id: string | null;
  session_code: string | null;
  table_labels: string[];
  reservation_id: string | null;
  reservation_code: string | null;
  reservation_starts_at: string | null;
  guest_name: string | null;
  items: OrderLine[];
  subtotal: string;
  tax_total: string;
  total: string;
  notes: string;
  placed_at: string;
  accepted_at: string | null;
  preparing_at: string | null;
  ready_at: string | null;
  served_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  sla: Sla | null;
  discount_total: string;
  payable_total: string;
  can_cancel: boolean;
  restaurant_name: string | null;
  restaurant_slug: string | null;
}

export interface TableView {
  session_id: string;
  code: string;
  status: string;
  restaurant_name: string;
  restaurant_slug: string;
  branch_id: string;
  branch_name: string;
  table_labels: string[];
  party_size: number;
  guest_name: string | null;
  opened_at: string;
  orders: Order[];
  subtotal: string;
  tax_total: string;
  total: string;
  discount_total: string;
  payable_total: string;
  promise: ServingPromise | null;
  ordering_open: boolean;
  server_time: string;
}

export const ORDER_STATUS_LABEL: Record<OrderStatus, string> = {
  placed: 'Sent to kitchen',
  accepted: 'Accepted',
  preparing: 'Preparing',
  ready: 'Ready',
  served: 'Served',
  cancelled: 'Cancelled',
};

/** A fresh key per checkout attempt; retries of the same attempt reuse it (server returns the original order). */
export function newIdempotencyKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

@Injectable({ providedIn: 'root' })
export class OrderingService {
  private readonly api = inject(ApiService);

  // ---------- guests at a table ----------
  joinTable(slug: string, code: string, pin: string): Observable<{ token: string; expires_at: string; session_id: string }> {
    return this.api.post(`public/restaurants/${encodeURIComponent(slug)}/table-sessions/join`, { code, pin });
  }
  tableView(token: string): Observable<TableView> {
    return this.api.getWithHeaders('table-session', { 'X-Table-Token': token });
  }
  tableOrder(token: string, items: OrderLineIn[], notes: string, key: string): Observable<Order> {
    return this.api.post('table-session/orders', { items, notes }, { 'X-Table-Token': token, 'Idempotency-Key': key });
  }
  tableCancel(token: string, orderId: string): Observable<Order> {
    return this.api.post(`table-session/orders/${orderId}/cancel`, {}, { 'X-Table-Token': token });
  }

  // ---------- signed-in customer ----------
  preorder(reservationId: string, items: OrderLineIn[], notes: string, key: string): Observable<Order> {
    return this.api.post(`me/reservations/${reservationId}/orders`, { items, notes }, { 'Idempotency-Key': key });
  }
  reservationOrders(reservationId: string): Observable<Order[]> {
    return this.api.get(`me/reservations/${reservationId}/orders`);
  }
  myOrders(): Observable<Order[]> {
    return this.api.get('me/orders');
  }
  cancelMine(orderId: string): Observable<Order> {
    return this.api.post(`me/orders/${orderId}/cancel`, {});
  }

  // ---------- staff ----------
  orders(branchId: string, active = true, date?: string): Observable<Order[]> {
    return this.api.get('restaurant/orders', { branch_id: branchId, active, date });
  }
  staffOrder(tableSessionId: string, items: OrderLineIn[], notes: string, key: string): Observable<Order> {
    return this.api.post('restaurant/orders', { table_session_id: tableSessionId, items, notes }, { 'Idempotency-Key': key });
  }
  setStatus(orderId: string, status: 'accepted' | 'preparing' | 'ready' | 'served'): Observable<Order> {
    return this.api.post(`restaurant/orders/${orderId}/status`, { status });
  }
  cancel(orderId: string, reason: string): Observable<Order> {
    return this.api.post(`restaurant/orders/${orderId}/cancel`, { reason });
  }
}

// ---------- menu helpers shared by storefront & staff ----------

/** Price shown for a dish at a branch (variants: "from" the cheapest). */
export function itemPrice(item: PublicItem, branchId: string | null): number {
  if (item.variants.length) return Math.min(...item.variants.map((v) => +v.price));
  const ov = item.branch_overrides.find((o) => o.branch_id === branchId);
  return ov?.price_override != null ? +ov.price_override : +item.price;
}

/** Why a dish cannot be ordered right now (null = it can). Mirrors the server's checks. */
export function unavailableReason(item: PublicItem, branchId: string | null, tz: string, at = new Date()): string | null {
  if (!item.is_available) return 'Sold out';
  const ov = item.branch_overrides.find((o) => o.branch_id === branchId);
  if (ov && !ov.is_available) return 'Not served at this branch';
  if (item.availability.length && !inWindow(item.availability, tz, at)) {
    return `Served ${windowsText(item.availability)}`;
  }
  return null;
}

function localParts(tz: string, at: Date): { weekday: number; hhmm: string } {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: tz,
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(at);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
  const weekday = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(get('weekday'));
  return { weekday, hhmm: `${get('hour').replace('24', '00')}:${get('minute')}` };
}

export function inWindow(windows: MenuWindow[], tz: string, at = new Date()): boolean {
  const { weekday, hhmm } = localParts(tz, at);
  return windows.some((w) => w.weekday === weekday && w.from_time.slice(0, 5) <= hhmm && hhmm < w.to_time.slice(0, 5));
}

/** "12:00–15:00" (same every day) or "Sat–Sun 09:00–12:00"-style summary. */
export function windowsText(windows: MenuWindow[]): string {
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const times = [...new Set(windows.map((w) => `${w.from_time.slice(0, 5)}–${w.to_time.slice(0, 5)}`))];
  const wd = [...new Set(windows.map((w) => w.weekday))].sort();
  const dayText = wd.length === 7 ? '' : `${wd.map((d) => days[d]).join(', ')} `;
  return `${dayText}${times.join(', ')}`;
}
