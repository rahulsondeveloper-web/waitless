import { CheckoutService } from './checkout.service';

describe('CheckoutService', () => {
  const svc = new CheckoutService();
  const w = window as unknown as { Cashfree?: unknown };

  afterEach(() => delete w.Cashfree);

  it('leaves the development mock checkout to the page', async () => {
    expect(svc.isMock({ url: '/pay/mock/x' })).toBe(true);
    expect(await svc.open({ url: '/pay/mock/x' })).toBe('mock');
  });

  it('opens the Cashfree checkout with the payment session in a popup', async () => {
    let mode = '';
    let opts: Record<string, unknown> = {};
    w.Cashfree = (o: { mode: string }) => {
      mode = o.mode;
      return {
        checkout: (x: Record<string, unknown>) => {
          opts = x;
          return Promise.resolve({ paymentDetails: { paymentMessage: 'ok' } });
        },
      };
    };
    const r = await svc.open({ provider: 'cashfree', payment_session_id: 'session_abc', order_id: 'wl_1', mode: 'production' });
    expect(r).toBe('submitted');
    expect(mode).toBe('production');
    expect(opts).toEqual({ paymentSessionId: 'session_abc', redirectTarget: '_modal' });
  });

  it('reports a closed or failed window as dismissed (the webhook decides)', async () => {
    w.Cashfree = () => ({ checkout: () => Promise.resolve({ error: { message: 'closed' } }) });
    expect(await svc.open({ payment_session_id: 's', mode: 'sandbox' })).toBe('dismissed');
  });

  it('says so when there is nothing it can open', async () => {
    expect(await svc.open({})).toBe('unavailable');
  });
});
