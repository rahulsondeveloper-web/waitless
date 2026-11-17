import { CheckoutService } from './checkout.service';

describe('CheckoutService', () => {
  const svc = new CheckoutService();

  it('leaves the development mock checkout to the page', async () => {
    expect(svc.isMock({ url: '/pay/mock/x' })).toBe(true);
    expect(await svc.open({ url: '/pay/mock/x' })).toBe('mock');
  });

  it('opens the Razorpay window with the order and reports the outcome', async () => {
    let options: Record<string, unknown> = {};
    (window as unknown as { Razorpay: unknown }).Razorpay = class {
      constructor(o: Record<string, unknown>) {
        options = o;
      }
      on(): void {}
      open(): void {
        (options['handler'] as () => void)();
      }
    };
    const r = await svc.open({ key_id: 'rzp_test_1', order_id: 'order_9', amount: 31500, currency: 'INR' }, { name: 'Urban Bites' });
    expect(r).toBe('submitted');
    expect(options['key']).toBe('rzp_test_1');
    expect(options['order_id']).toBe('order_9');
    expect(options['name']).toBe('Urban Bites');
    delete (window as unknown as { Razorpay?: unknown }).Razorpay;
  });

  it('says so when there is nothing it can open', async () => {
    expect(await svc.open({})).toBe('unavailable');
  });
});
