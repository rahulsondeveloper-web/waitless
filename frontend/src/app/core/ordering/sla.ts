import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';

/** Serving timer of one order (PRD §14). The server is authoritative; the browser only counts down. */
export interface Sla {
  started_at: string;
  deadline_at: string;
  start_reason: 'accepted' | 'arrival_confirmed';
  status: 'running' | 'served' | 'cancelled';
  ended_at: string | null;
  eligible: boolean;
  discount_pct: string;
  discount_amount: string;
  next_boundary_at: string | null;
  serving_minutes: number;
  initial_pct: string;
  interval_minutes: number;
  increment_pct: string;
  max_pct: string;
  base: 'food_subtotal' | 'order_total';
}

export interface ServingPromise {
  is_active: boolean;
  serving_minutes: number;
  initial_pct: string;
  interval_minutes: number;
  increment_pct: string;
  max_pct: string;
}

export type OrderType = 'walk_in' | 'booking' | 'staff' | 'paid_preorder';

export interface DiscountPolicy extends ServingPromise {
  eligible_order_types: OrderType[];
  base: 'food_subtotal' | 'order_total';
  is_default?: boolean;
  updated_at?: string | null;
}

export const ORDER_TYPE_LABEL: Record<OrderType, string> = {
  walk_in: 'Walk-in guests',
  booking: 'Guests with a booking',
  staff: 'Orders placed by a waiter',
  paid_preorder: 'Paid pre-orders (timer starts at arrival)',
};

type Rule = Pick<ServingPromise, 'serving_minutes' | 'initial_pct' | 'interval_minutes' | 'increment_pct' | 'max_pct'>;

/** Same formula as the server (decision D14): 0 up to the promise, then initial + increment per interval, capped. */
export function discountPct(elapsedMs: number, p: Rule): number {
  const over = elapsedMs - p.serving_minutes * 60_000;
  if (over <= 0) return 0;
  const steps = Math.ceil(over / (p.interval_minutes * 60_000));
  return Math.min(+p.max_pct, +p.initial_pct + (steps - 1) * +p.increment_pct);
}

/** The discount an order shows at `nowMs` (served/cancelled: the server's frozen value). */
export function slaPct(sla: Sla, nowMs: number): number {
  if (!sla.eligible || sla.status !== 'running') return +sla.discount_pct;
  return discountPct(nowMs - Date.parse(sla.started_at), sla);
}

/** "Served in 15 min — or 2% off, +2% every 5 min (up to 20%)". */
export function promiseText(p: ServingPromise): string {
  if (!p.is_active) return `We aim to serve within ${p.serving_minutes} minutes.`;
  const more = +p.increment_pct > 0 ? `, +${+p.increment_pct}% every ${p.interval_minutes} min more (up to ${+p.max_pct}%)` : '';
  return `Served within ${p.serving_minutes} min of the kitchen accepting — or ${+p.initial_pct}% off that order${more}.`;
}

/** mm:ss (or h:mm:ss) for a duration in ms. */
export function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

@Injectable({ providedIn: 'root' })
export class DiscountPolicyService {
  private readonly api = inject(ApiService);

  get(): Observable<DiscountPolicy> {
    return this.api.get('restaurant/discount-policy');
  }
  save(p: DiscountPolicy): Observable<DiscountPolicy> {
    const { is_default: _d, updated_at: _u, ...body } = p;
    return this.api.put('restaurant/discount-policy', body);
  }
}
