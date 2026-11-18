import { APIRequestContext, Browser, Page, expect, test } from '@playwright/test';

/** Phase 10: guest Finish → pay online → receipt; staff split, discount, cash with change, card, invoice, close. */

const SLUG = 'e2e-urban-bites';
const OWNER = 'e2e.owner@urbanbites.example.com';
const OWNER_PASSWORD = 'Demo-pass-123';

async function api(request: APIRequestContext) {
  const r = await request.post('/api/v1/auth/login', { data: { identifier: OWNER, password: OWNER_PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await r.json()).access_token}` };
  const me = await (await request.get('/api/v1/restaurant/me', { headers })).json();
  const branch = me.branches.find((b: { is_primary: boolean }) => b.is_primary) ?? me.branches[0];
  return { headers, branchId: branch.id as string };
}

interface Dish {
  id: string;
  is_available: boolean;
  is_archived: boolean;
  variants: unknown[];
  availability: unknown[];
}

/** Seat guests at a free table (from the end of the floor) and place an order for them. */
async function seatAndOrder(request: APIRequestContext, guest: string, lines: number[]) {
  const { headers, branchId } = await api(request);
  const board = await (await request.get(`/api/v1/restaurant/tables/board?branch_id=${branchId}`, { headers })).json();
  for (const t of board.tables.filter((x: { status: string }) => x.status === 'available').reverse()) {
    const r = await request.post('/api/v1/restaurant/table-sessions', { headers, data: { table_id: t.id, party_size: 2, guest_name: guest } });
    if (r.status() !== 201) continue;
    const s = await r.json();
    const menu = await (await request.get('/api/v1/restaurant/menu', { headers })).json();
    const dishes = (menu.items as Dish[])
      .filter((i: Dish) => i.is_available && !i.is_archived && !i.variants.length && !i.availability.length);
    const order = await (
      await request.post('/api/v1/restaurant/orders', {
        headers,
        data: { table_session_id: s.session.id, items: lines.map((q, i) => ({ menu_item_id: dishes[i].id, quantity: q })) },
      })
    ).json();
    for (const st of ['accepted', 'preparing', 'ready', 'served']) {
      await request.post(`/api/v1/restaurant/orders/${order.id}/status`, { headers, data: { status: st } });
    }
    return { headers, branchId, session: s.session, pin: s.pin as string, label: t.label as string, tableId: t.id as string };
  }
  throw new Error('no free table');
}

async function ownerPage(browser: Browser, path: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto('/login');
  await page.getByLabel('Email or mobile number').fill(OWNER);
  await page.getByLabel('Password', { exact: true }).fill(OWNER_PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/restaurant-admin/, { timeout: 15_000 });
  await page.goto(path);
  return page;
}

test('guest presses Finish, pays online and gets the receipt; staff then closes the table', async ({ page, browser }) => {
  test.setTimeout(90_000);
  const seated = await seatAndOrder(page.request, `Bill Guest ${Date.now()}`, [2]);

  await page.goto(`/r/${SLUG}`);
  await page.getByTestId('have-order-id').click();
  await page.getByTestId('join-code').fill(seated.session.public_code);
  await page.getByTestId('join-pin').fill(seated.pin);
  await page.getByRole('button', { name: 'Open my table' }).click();
  await expect(page.getByTestId('table-view')).toContainText(seated.session.public_code);

  await page.getByTestId('finish').click();
  const popup = page.getByTestId('finish-popup');
  await popup.getByTestId('finish-confirm').click();
  // The popup shows the final bill with every charge, and Pay now.
  await expect(popup.getByTestId('popup-bill')).toBeVisible();
  await expect(popup.getByTestId('bill-lines').locator('li')).toHaveCount(1);
  await expect(popup.getByTestId('summary-total')).toBeVisible();
  await popup.getByTestId('popup-pay-now').click();

  // Checkout: UPI ID / QR / card through the gateway (mock in development).
  await expect(page).toHaveURL(new RegExp(`/r/${SLUG}/checkout/`));
  await page.getByTestId('pay-gateway').getByTestId('checkout-pay-online').click();
  await page.getByTestId('mock-pay').click();
  await expect(page.getByTestId('checkout-paid')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('download-invoice')).toHaveAttribute('href', /\/invoices\/.+\/pdf\?t=/);

  await page.goto(`/r/${SLUG}/session`);
  const bill = page.getByTestId('guest-bill');
  await expect(bill).toContainText('Paid');
  await expect(page.getByTestId('order-more')).toHaveCount(0); // no more orders after Finish
  await expect(bill.getByTestId('receipt')).toHaveAttribute('href', /\/invoices\/.+\/pdf\?t=/);

  const staff = await ownerPage(browser, '/restaurant-admin/billing');
  const card = staff.getByTestId('billing-table').filter({ hasText: `Table ${seated.label}` });
  await expect(card).toContainText('Paid');
  await card.click();
  await expect(staff.getByTestId('bill')).toContainText('Online');
  await staff.getByTestId('close-table').click();
  await expect(staff.getByText(`Table ${seated.label} closed`)).toBeVisible();
  await page.request.patch(`/api/v1/restaurant/tables/${seated.tableId}/status`, { headers: seated.headers, data: { status: 'available' } });
  await staff.context().close();
});

test('cashier splits a bill, gives a discount, takes cash with change and a card, and closes the table', async ({ page, browser }) => {
  test.setTimeout(90_000);
  const seated = await seatAndOrder(page.request, `Split Guest ${Date.now()}`, [1, 2]);
  const staff = await ownerPage(browser, '/restaurant-admin/billing');
  await staff.getByTestId('billing-table').filter({ hasText: `Table ${seated.label}` }).click();
  const first = staff.getByTestId('bill').first();
  await expect(first.locator('tbody tr')).toHaveCount(2);

  // Split the second line to its own bill.
  await first.locator('tbody tr').nth(1).locator('input[type=checkbox]').check();
  await first.getByTestId('split').click();
  await expect(staff.getByTestId('bill')).toHaveCount(2);
  const b1 = staff.getByTestId('bill').nth(0);
  const b2 = staff.getByTestId('bill').nth(1);
  await expect(b1).toContainText('Bill 1');
  await expect(b2).toContainText('Bill 2');

  // 10 % discount with a reason on bill 1.
  await b1.getByTestId('discount').click();
  const d = staff.getByRole('dialog');
  await d.getByTestId('disc-value').fill('10');
  await d.getByTestId('disc-reason').fill('Regular guest');
  await d.getByTestId('disc-save').click();
  await expect(b1.getByTestId('bill-totals')).toContainText('Discount 10%');

  // Cash: hand over a round note, see the change.
  await b1.getByTestId('take-payment').click();
  const pay = staff.getByRole('dialog');
  const due = Number((await pay.getByTestId('pay-amount').inputValue()) || '0');
  const note = Math.ceil(due / 100) * 100 + 100;
  await pay.getByTestId('method-cash').click();
  await pay.getByTestId('pay-tendered').fill(String(note));
  await expect(pay.getByTestId('pay-change')).toContainText('Give back');
  await pay.getByTestId('pay-confirm').click();
  await expect(b1).toContainText('Paid');
  await expect(b1.getByTestId('invoice-pdf')).toContainText(/INV-\d{6}/);

  // Card for bill 2.
  await expect(staff.getByTestId('close-table')).toBeDisabled();
  await b2.getByTestId('take-payment').click();
  await staff.getByRole('dialog').getByTestId('method-card').click();
  await staff.getByRole('dialog').getByTestId('pay-confirm').click();
  await expect(b2).toContainText('Paid');

  await staff.getByTestId('close-table').click();
  await expect(staff.getByText(`Table ${seated.label} closed`)).toBeVisible();
  await page.request.patch(`/api/v1/restaurant/tables/${seated.tableId}/status`, { headers: seated.headers, data: { status: 'available' } });

  const payments = await ownerPage(browser, '/restaurant-admin/payments');
  await expect(payments.getByTestId('payments-table')).toContainText('Cash');
  await expect(payments.getByTestId('payments-table')).toContainText('Card');
  await expect(payments.getByTestId('invoices-table')).toContainText('INV-');
  await payments.context().close();
  await staff.context().close();
});
