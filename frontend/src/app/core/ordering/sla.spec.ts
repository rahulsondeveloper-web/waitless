import { TestBed } from '@angular/core/testing';

import { ServingTimerComponent, SecondTicker } from '../../shared/ui/serving-timer/serving-timer.component';
import { Order } from './ordering.service';
import { Sla, clock, discountPct, promiseText, slaPct } from './sla';

const POLICY = { serving_minutes: 15, initial_pct: '2', interval_minutes: 5, increment_pct: '2', max_pct: '20' };
const MIN = 60_000;

describe('serving-time discount (same table as the server)', () => {
  it.each([
    [0, 0],
    [15, 0],
    [15.01, 2],
    [16, 2],
    [20, 2],
    [21, 4],
    [35, 8],
    [120, 20],
  ])('%s min → %s %%', (minutes, pct) => {
    expect(discountPct(minutes * MIN, POLICY)).toBe(pct);
  });

  it('describes the promise and formats the countdown', () => {
    expect(promiseText({ is_active: true, ...POLICY })).toBe(
      'Served within 15 min of the kitchen accepting — or 2% off that order, +2% every 5 min more (up to 20%).',
    );
    expect(promiseText({ is_active: false, ...POLICY })).toBe('We aim to serve within 15 minutes.');
    expect(clock(12 * MIN + 40_000)).toBe('12:40');
    expect(clock(65 * MIN)).toBe('1:05:00');
  });
});

const T0 = Date.parse('2026-11-17T12:00:00Z');
const sla = (over: Partial<Sla> = {}): Sla => ({
  started_at: new Date(T0).toISOString(),
  deadline_at: new Date(T0 + 15 * MIN).toISOString(),
  start_reason: 'accepted',
  status: 'running',
  ended_at: null,
  eligible: true,
  discount_pct: '0.00',
  discount_amount: '0.00',
  next_boundary_at: null,
  ...POLICY,
  base: 'food_subtotal',
  ...over,
});

const order = (over: Partial<Order> = {}): Order =>
  ({
    id: 'o1',
    order_type: 'walk_in',
    status: 'accepted',
    table_session_id: 's1',
    subtotal: '1000.00',
    total: '1050.00',
    sla: sla(),
    ...over,
  }) as Order;

describe('slaPct', () => {
  it('counts live while running and keeps the frozen value once served', () => {
    expect(slaPct(sla(), T0 + 21 * MIN)).toBe(4);
    expect(slaPct(sla({ status: 'served', discount_pct: '2.00' }), T0 + 90 * MIN)).toBe(2);
    expect(slaPct(sla({ eligible: false }), T0 + 90 * MIN)).toBe(0);
  });
});

describe('ServingTimerComponent', () => {
  function render(o: Order, now: number): string {
    TestBed.resetTestingModule();
    TestBed.inject(SecondTicker).now.set(now);
    const f = TestBed.createComponent(ServingTimerComponent);
    f.componentRef.setInput('order', o);
    f.detectChanges();
    const parts = [...(f.nativeElement as HTMLElement).querySelectorAll('.main, .extra')].map((e) => e.textContent!.trim());
    return parts.join(' ');
  }

  it('counts down before the deadline', () => {
    expect(render(order(), T0 + 2 * MIN + 20_000)).toBe('12:40 left to serve');
  });

  it('shows the discount and amount when late', () => {
    expect(render(order(), T0 + 21 * MIN)).toBe('Running late · 6:00 · 4% off (₹40)');
  });

  it('explains when the timer will start', () => {
    expect(render(order({ status: 'placed', sla: null }), T0)).toBe('Timer starts when the kitchen accepts');
    expect(render(order({ status: 'placed', sla: null, order_type: 'paid_preorder', table_session_id: null }), T0)).toBe(
      'Timer starts when you arrive',
    );
  });

  it('shows the final result once served', () => {
    const served = order({
      status: 'served',
      sla: sla({ status: 'served', ended_at: new Date(T0 + 18 * MIN).toISOString(), discount_pct: '2.00' }),
    });
    expect(render(served, T0 + 60 * MIN)).toBe('Served in 18 min · 2% off (₹20)');
  });
});
