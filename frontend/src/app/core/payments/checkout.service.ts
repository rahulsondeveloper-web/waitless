import { Injectable } from '@angular/core';

/**
 * Opens the payment provider's checkout (Phase 12). The server decides the provider:
 * - mock (development): `checkout.url` → the caller shows its own test checkout;
 * - Razorpay: `checkout.key_id` + `order_id` → the official Razorpay window (checkout.js, loaded on demand).
 *
 * The browser's "success" is never trusted: the server marks things paid only from the signature-verified
 * webhook (decision D57), so callers just refresh after the window closes.
 */

export interface CheckoutData {
  url?: string;
  key_id?: string;
  order_id?: string;
  amount?: number;
  currency?: string;
  [k: string]: unknown;
}

export interface CheckoutOptions {
  name?: string;
  description?: string;
  prefill?: { name?: string; contact?: string; email?: string };
  color?: string;
}

/** 'submitted' = the guest finished in the window (the webhook confirms), 'dismissed' = closed it. */
export type CheckoutResult = 'mock' | 'submitted' | 'dismissed' | 'unavailable';

interface RazorpayCtor {
  new (options: Record<string, unknown>): { open(): void; on(event: string, cb: (r: unknown) => void): void };
}

const SCRIPT = 'https://checkout.razorpay.com/v1/checkout.js';
let loading: Promise<RazorpayCtor | null> | null = null;

function loadRazorpay(): Promise<RazorpayCtor | null> {
  const w = window as unknown as { Razorpay?: RazorpayCtor };
  if (w.Razorpay) return Promise.resolve(w.Razorpay);
  loading ??= new Promise((resolve) => {
    const s = document.createElement('script');
    s.src = SCRIPT;
    s.async = true;
    s.onload = () => resolve((window as unknown as { Razorpay?: RazorpayCtor }).Razorpay ?? null);
    s.onerror = () => {
      loading = null;
      resolve(null);
    };
    document.head.appendChild(s);
  });
  return loading;
}

@Injectable({ providedIn: 'root' })
export class CheckoutService {
  /** True when the caller must show its own (development) test checkout. */
  isMock(c: CheckoutData): boolean {
    return !!c.url;
  }

  async open(c: CheckoutData, opts: CheckoutOptions = {}): Promise<CheckoutResult> {
    if (c.url) return 'mock';
    if (!c.key_id || !c.order_id) return 'unavailable';
    const Razorpay = await loadRazorpay();
    if (!Razorpay) return 'unavailable';
    return new Promise<CheckoutResult>((resolve) => {
      const rzp = new Razorpay({
        key: c.key_id,
        order_id: c.order_id,
        amount: c.amount,
        currency: c.currency ?? 'INR',
        name: opts.name ?? 'WaitLess',
        description: opts.description,
        prefill: opts.prefill,
        theme: { color: opts.color ?? '#0a7c86' },
        handler: () => resolve('submitted'),
        modal: { ondismiss: () => resolve('dismissed'), confirm_close: true },
      });
      rzp.on('payment.failed', () => undefined); // the window lets the guest retry; the webhook decides
      rzp.open();
    });
  }
}
