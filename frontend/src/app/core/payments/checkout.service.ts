import { Injectable } from '@angular/core';

/**
 * Opens the payment provider's checkout. The server decides the provider:
 * - mock (development): `checkout.url` → the caller shows its own test checkout;
 * - Cashfree: `checkout.payment_session_id` → Cashfree's checkout (JS SDK v3, loaded on demand) in a
 *   popup over the page: UPI ID, UPI QR, cards, net banking and wallets.
 *
 * The browser's "success" is never trusted: the server marks things paid only from the signature-verified
 * webhook (decision D57), so callers just refresh after the window closes.
 */

export interface CheckoutData {
  url?: string;
  provider?: string;
  payment_session_id?: string;
  order_id?: string;
  mode?: 'sandbox' | 'production';
  [k: string]: unknown;
}

export interface CheckoutOptions {
  name?: string;
  description?: string;
}

/** 'submitted' = the guest finished in the window (the webhook confirms), 'dismissed' = closed it or it failed. */
export type CheckoutResult = 'mock' | 'submitted' | 'dismissed' | 'unavailable';

interface CashfreeResult {
  error?: { message?: string };
  paymentDetails?: unknown;
  redirect?: boolean;
}

interface CashfreeInstance {
  checkout(opts: { paymentSessionId: string; redirectTarget: '_modal' | '_self' | '_blank' }): Promise<CashfreeResult>;
}

type CashfreeFactory = (opts: { mode: 'sandbox' | 'production' }) => CashfreeInstance;

const SCRIPT = 'https://sdk.cashfree.com/js/v3/cashfree.js';
let loading: Promise<CashfreeFactory | null> | null = null;

function loadCashfree(): Promise<CashfreeFactory | null> {
  const w = window as unknown as { Cashfree?: CashfreeFactory };
  if (w.Cashfree) return Promise.resolve(w.Cashfree);
  loading ??= new Promise((resolve) => {
    const s = document.createElement('script');
    s.src = SCRIPT;
    s.async = true;
    s.onload = () => resolve((window as unknown as { Cashfree?: CashfreeFactory }).Cashfree ?? null);
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

  // `opts` is kept for callers; Cashfree shows the merchant name from its dashboard.
  async open(c: CheckoutData, _opts: CheckoutOptions = {}): Promise<CheckoutResult> {
    if (c.url) return 'mock';
    if (!c.payment_session_id) return 'unavailable';
    const Cashfree = await loadCashfree();
    if (!Cashfree) return 'unavailable';
    try {
      const result = await Cashfree({ mode: c.mode === 'production' ? 'production' : 'sandbox' }).checkout({
        paymentSessionId: c.payment_session_id,
        redirectTarget: '_modal',
      });
      if (result.error) return 'dismissed'; // closed, or the payment failed — the webhook decides either way
      return 'submitted';
    } catch {
      return 'unavailable';
    }
  }
}
