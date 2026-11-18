import { APIRequestContext, Browser, Page, expect, test } from '@playwright/test';

/** Guest service: call the waiter, restaurant Wi-Fi, bigger kitchen timer, split by person / equal shares,
 * invoice with names, review after paying. */

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

interface Dish {
  id: string;
  is_available: boolean;
  is_archived: boolean;
  variants: unknown[];
  availability: unknown[];
}

/** Seat a party at a free table (from the end of the floor) and return its order ID + PIN + table token. */
async function seat(request: APIRequestContext, guest: string) {
  const { headers, branchId } = await api(request);
  const board = await (await request.get(`/api/v1/restaurant/tables/board?branch_id=${branchId}`, { headers })).json();
  for (const t of board.tables.filter((x: { status: string; session: unknown }) => x.status === 'available' && !x.session).reverse()) {
    const r = await request.post('/api/v1/restaurant/table-sessions', { headers, data: { table_id: t.id, party_size: 2, guest_name: guest } });
    if (r.status() !== 201) continue;
    const s = await r.json();
    const join = await request.post(`/api/v1/public/restaurants/${SLUG}/table-sessions/join`, {
      data: { code: s.session.public_code, pin: s.pin },
    });
    const token = (await join.json()).token as string;
    const menu = await (await request.get('/api/v1/restaurant/menu', { headers })).json();
    const dishes = (menu.items as Dish[]).filter((i) => i.is_available && !i.is_archived && !i.variants.length && !i.availability.length);
    return { headers, branchId, code: s.session.public_code as string, pin: s.pin as string, label: t.label as string, tableId: t.id as string, sessionId: s.session.id as string, token, dishes };
  }
  throw new Error('no free table');
}

async function serveAll(request: APIRequestContext, headers: Record<string, string>, orderId: string) {
  for (const st of ['accepted', 'preparing', 'ready', 'served']) {
    await request.post(`/api/v1/restaurant/orders/${orderId}/status`, { headers, data: { status: st } });
  }
}

async function joinInBrowser(page: Page, code: string, pin: string, name: string) {
  await page.goto(`/r/${SLUG}/session`);
  await page.getByTestId('join-code').fill(code);
  await page.getByTestId('join-name').fill(name);
  await page.getByTestId('join-pin').fill(pin);
  await page.getByRole('button', { name: 'Open my table' }).click();
  await expect(page.getByTestId('table-view')).toContainText(code);
}

test('a seated guest sees the Wi-Fi, calls the waiter, and the staff alert clears; the kitchen timer is big', async ({ page, browser }) => {
  test.setTimeout(120_000);
  const t = await seat(page.request, `Call Guest ${Date.now()}`);
  await page.request.put('/api/v1/restaurant/guest-wifi', { headers: t.headers, data: { name: 'UB-Guest', password: 'tasty-food-9' } });
  const staff = await ownerPage(browser, '/restaurant-admin/tables');
  try {
    // Not seated yet: no Wi-Fi and no call button.
    await page.goto(`/r/${SLUG}`);
    await expect(page.getByTestId('have-order-id')).toBeVisible();
    await expect(page.getByTestId('wifi-button')).toHaveCount(0);
    await expect(page.getByTestId('call-waiter')).toHaveCount(0);

    await joinInBrowser(page, t.code, t.pin, 'Dinesh');
    await page.goto(`/r/${SLUG}`);
    await page.getByTestId('wifi-button').click();
    await expect(page.getByTestId('wifi-tip-name')).toHaveText('UB-Guest');
    await expect(page.getByTestId('wifi-tip-password')).toHaveText('tasty-food-9');

    // One tap: Water. Every option then waits 2 minutes.
    await page.getByTestId('call-waiter').click();
    await page.getByTestId('call-water').click();
    await expect(page.getByTestId('call-sent')).toContainText('Water');
    await expect(page.getByTestId('call-wait')).toContainText(/1:[0-5]\d|2:00/);
    await expect(page.getByTestId('call-tissue')).toBeDisabled();

    // Staff on any admin page get the alert with the table number and clear it once there.
    const call = staff.getByTestId('service-call').filter({ hasText: `Table ${t.label}` });
    await expect(call).toContainText('Water', { timeout: 15_000 });
    await expect(call).toContainText('Dinesh');
    await call.getByTestId('service-done').click();
    await expect(call).toHaveCount(0);
    await expect(page.getByTestId('call-sent')).toContainText('seen to it', { timeout: 15_000 });

    // Kitchen: the timer is large; a new ticket shows how long it has waited.
    const order = await (
      await page.request.post('/api/v1/table-session/orders', {
        headers: { 'X-Table-Token': t.token },
        data: { items: [{ menu_item_id: t.dishes[0].id }], guest_name: 'Dinesh' },
      })
    ).json();
    await staff.goto('/restaurant-admin/kitchen');
    const ticket = staff.getByTestId('ticket').filter({ hasText: `Table ${t.label}` });
    await expect(ticket.getByTestId('serving-timer')).toContainText('Waiting');
    await ticket.getByRole('button', { name: 'Accept' }).click();
    await expect(ticket.getByTestId('serving-timer')).toContainText('left to serve');
    await expect(ticket.locator('.timer.large')).toBeVisible();

    // Clean up: serve, pay at the counter (the table closes by itself).
    await serveAll(page.request, t.headers, order.id);
    const bills = await (await page.request.post(`/api/v1/restaurant/table-sessions/${t.sessionId}/bill`, { headers: t.headers })).json();
    for (const b of bills.bills) {
      if (+b.due > 0) await page.request.post(`/api/v1/restaurant/bills/${b.id}/payments`, { headers: t.headers, data: { method: 'cash', amount: b.due } });
    }
  } finally {
    await page.request.put('/api/v1/restaurant/guest-wifi', { headers: t.headers, data: { name: '', password: '' } });
    await page.request.patch(`/api/v1/restaurant/tables/${t.tableId}/status`, { headers: t.headers, data: { status: 'available' } });
    await staff.context().close();
  }
});

test('the table splits the bill by person and in equal shares, downloads the invoice with names and leaves a review', async ({ page }) => {
  test.setTimeout(120_000);
  const t = await seat(page.request, `Split Party ${Date.now()}`);
  const guestHeaders = { 'X-Table-Token': t.token };
  for (const [dish, name] of [
    [t.dishes[0], 'Riya'],
    [t.dishes[1], 'Kabir'],
  ] as const) {
    const o = await (
      await page.request.post('/api/v1/table-session/orders', { headers: guestHeaders, data: { items: [{ menu_item_id: dish.id }], guest_name: name } })
    ).json();
    await serveAll(page.request, t.headers, o.id);
  }
  try {
    await joinInBrowser(page, t.code, t.pin, 'Riya');
    await page.getByTestId('finish').click();
    await page.getByTestId('finish-confirm').click();
    await page.getByTestId('popup-pay-now').click();
    await expect(page.getByTestId('checkout-card')).toContainText('Order Summary');
    await expect(page.getByTestId('payment-card')).toContainText('Pay at Restaurant');

    // By person: one bill each.
    await page.getByTestId('split-person').click();
    await page.getByTestId('split-by-person').click();
    const people = page.getByTestId('person-bills');
    await expect(people.locator('li')).toHaveCount(2);
    await expect(people).toContainText('Riya');
    await expect(people).toContainText('Kabir');

    // Riya pays her own bill by card (test payment in development).
    await page.getByTestId('pay-gateway').getByTestId('checkout-pay-online').click();
    await page.getByTestId('mock-pay').click();
    await expect(page.getByTestId('checkout-paid')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('download-invoice-names')).toHaveAttribute('href', /names=true/);

    // Kabir's bill: two friends pay it in equal shares.
    const all = await (await page.request.get('/api/v1/table-session/bills', { headers: guestHeaders })).json();
    const kabir = all.bills.find((b: { status: string; lines: unknown[] }) => b.status === 'open' && b.lines.length);
    await page.goto(`/r/${SLUG}/checkout/${kabir.id}`);
    await page.getByTestId('split-equal').click();
    await expect(page.getByTestId('split-people')).toHaveText('2');
    const half = (+kabir.grand_total / 2).toFixed(2);
    await expect(page.getByTestId('split-share')).toContainText(String(Math.floor(+half)));
    await page.getByTestId('checkout-pay-online').click();
    await page.getByTestId('mock-pay').click();
    await expect(page.getByText('Paid so far')).toBeVisible({ timeout: 15_000 });
    // The second share is paid at the counter → last bill paid → the table closes by itself.
    const after = await (await page.request.get('/api/v1/table-session/bills', { headers: guestHeaders })).json();
    const rest = after.bills.find((b: { id: string }) => b.id === kabir.id);
    await page.request.post(`/api/v1/restaurant/bills/${kabir.id}/payments`, { headers: t.headers, data: { method: 'cash', amount: rest.due } });
    await expect(page.getByTestId('checkout-paid')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('checkout-closed')).toBeVisible();

    // Review after paying; it appears on the restaurant's page.
    const comment = `Lovely dinner ${Date.now() % 100000}`;
    await page.getByTestId('star-5').click();
    await page.getByTestId('review-comment').fill(comment);
    await page.getByTestId('review-submit').click();
    await expect(page.getByTestId('review-sent')).toBeVisible();
    await page.goto(`/r/${SLUG}`);
    await expect(page.getByTestId('home-reviews')).toContainText(comment, { timeout: 15_000 });
  } finally {
    await page.request.patch(`/api/v1/restaurant/tables/${t.tableId}/status`, { headers: t.headers, data: { status: 'available' } });
  }
});
