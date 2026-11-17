import { APIRequestContext, Browser, Page, expect, test } from '@playwright/test';

/** Phases 7–8: "Have an order ID?" → order from the table → kitchen display → served (live) with the serving
 * timer; waiter orders; the discount settings screen. */

const SLUG = 'e2e-urban-bites';
const OWNER = 'e2e.owner@urbanbites.example.com';
const OWNER_PASSWORD = 'Demo-pass-123';

async function ownerToken(request: APIRequestContext): Promise<string> {
  const r = await request.post('/api/v1/auth/login', { data: { identifier: OWNER, password: OWNER_PASSWORD } });
  expect(r.ok()).toBeTruthy();
  return (await r.json()).access_token;
}

/** Seat guests at any free table through the API → { code, pin, label }. */
async function seatGuests(
  request: APIRequestContext,
  guest: string,
): Promise<{ code: string; pin: string; label: string; release: () => Promise<void> }> {
  const token = await ownerToken(request);
  const headers = { Authorization: `Bearer ${token}` };
  const me = await (await request.get('/api/v1/restaurant/me', { headers })).json();
  const branch = me.branches.find((b: { is_primary: boolean }) => b.is_primary) ?? me.branches[0];
  const board = await (await request.get(`/api/v1/restaurant/tables/board?branch_id=${branch.id}`, { headers })).json();
  // From the end of the floor: the booking tests hold the first tables (T1…) for their guests.
  for (const t of board.tables.filter((x: { status: string }) => x.status === 'available').reverse()) {
    const r = await request.post('/api/v1/restaurant/table-sessions', {
      headers,
      data: { table_id: t.id, party_size: 2, guest_name: guest },
    });
    if (r.status() === 201) {
      const s = await r.json();
      const release = async () => {
        // Guests left: free the table so later tests (and the other device project) find one.
        await request.post(`/api/v1/restaurant/table-sessions/${s.session.id}/close`, { headers });
        await request.patch(`/api/v1/restaurant/tables/${t.id}/status`, { headers, data: { status: 'available' } });
      };
      return { code: s.session.public_code, pin: s.pin, label: t.label, release };
    }
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

test('guest enters the order ID + PIN, orders, and follows it live to Served', async ({ page, browser }) => {
  test.setTimeout(90_000);
  const guest = `Table Guest ${Date.now()}`;
  const seated = await seatGuests(page.request, guest);

  await page.goto(`/r/${SLUG}`);
  await page.getByTestId('have-order-id').click();
  await page.getByTestId('join-code').fill(seated.code);
  await page.getByTestId('join-pin').fill(seated.pin);
  await page.getByRole('button', { name: 'Open my table' }).click();
  await expect(page.getByTestId('table-view')).toContainText(seated.code);
  await expect(page.getByTestId('table-view')).toContainText(`Table ${seated.label}`);

  await page.getByTestId('order-more').click();
  await page.getByRole('button', { name: /^Add / }).first().click();
  await page.getByTestId('add-to-cart').click();
  await expect(page.getByTestId('cart-count')).toHaveText('1');
  await page.getByTestId('cart-bar').click();
  await expect(page.getByTestId('cart-line')).toHaveCount(1);
  await page.getByTestId('place-order').click();

  await expect(page).toHaveURL(new RegExp(`/r/${SLUG}/session$`));
  const order = page.getByTestId('table-order').first();
  await expect(order).toContainText('Sent to kitchen');
  await expect(page.getByTestId('serving-promise')).toContainText('Served within 15 min');
  await expect(order.getByTestId('serving-timer')).toHaveText(/Timer starts when the kitchen accepts/);

  // Kitchen moves the ticket along; the guest's page follows without reloading.
  const kitchen = await ownerPage(browser, '/restaurant-admin/kitchen');
  const ticket = kitchen.getByTestId('ticket').filter({ hasText: `Table ${seated.label}` });
  await expect(ticket).toBeVisible();
  await ticket.getByRole('button', { name: 'Accept' }).click();
  await expect(order).toContainText('Accepted', { timeout: 15_000 });
  // The 15-minute timer starts when the kitchen accepts (PRD §14) — on the guest's phone and on the ticket.
  await expect(order.getByTestId('serving-timer')).toHaveText(/1[45]:\d\d left to serve/);
  await expect(kitchen.getByTestId('ticket').filter({ hasText: `Table ${seated.label}` }).getByTestId('serving-timer')).toContainText(
    'left to serve',
  );
  await kitchen.getByTestId('ticket').filter({ hasText: `Table ${seated.label}` }).getByRole('button', { name: 'Start cooking' }).click();
  await kitchen.getByTestId('ticket').filter({ hasText: `Table ${seated.label}` }).getByRole('button', { name: 'Ready' }).click();
  await expect(order).toContainText('Ready', { timeout: 15_000 });
  await kitchen.getByTestId('ticket').filter({ hasText: `Table ${seated.label}` }).getByRole('button', { name: 'Served' }).click();
  await expect(order).toContainText('Served', { timeout: 15_000 });
  await expect(order.getByTestId('serving-timer')).toHaveText(/Served in \d+ min/);
  await expect(page.getByTestId('table-total')).not.toHaveText('₹0');
  await kitchen.context().close();
  await seated.release();
});

test('waiter places an order for a seated table from the Orders page', async ({ page, browser }) => {
  test.setTimeout(60_000);
  const guest = `Waiter Guest ${Date.now()}`;
  const seated = await seatGuests(page.request, guest);
  const staff = await ownerPage(browser, '/restaurant-admin/orders');
  await staff.getByTestId('new-order').click();
  const dialog = staff.getByRole('dialog');
  const table = dialog.getByTestId('order-table');
  const option = await table.locator('option', { hasText: seated.code }).getAttribute('value');
  await table.selectOption(option!);
  const dish = await dialog.locator('datalist#dishes option').first().getAttribute('value');
  await dialog.getByTestId('order-dish').fill(dish!);
  await dialog.getByTestId('order-dish').dispatchEvent('change');
  await dialog.getByTestId('order-add-line').click();
  await dialog.getByTestId('order-send').click();
  const row = staff.getByTestId('order-row').filter({ hasText: guest });
  await expect(row).toContainText('Sent to kitchen');
  await expect(row).toContainText(seated.code);
  await staff.context().close();
  await seated.release();
});

test('owner sees the serving-time discount policy and what guests get', async ({ browser }) => {
  const owner = await ownerPage(browser, '/restaurant-admin/discounts');
  await expect(owner.getByRole('heading', { name: 'Discount settings' })).toBeVisible();
  const preview = owner.getByTestId('policy-preview');
  await expect(preview).toContainText('Up to 15 min');
  await expect(preview.getByRole('row', { name: /15–20 min/ })).toContainText('2%');
  await expect(preview.getByRole('row', { name: /20–25 min/ })).toContainText('4%');
  await expect(preview).toContainText('20%');

  // Editing updates the explanation and table immediately (not saved: other tests share this restaurant).
  await owner.getByTestId('policy-serving').fill('20');
  await expect(owner.getByTestId('policy-summary')).toContainText('Served within 20 min');
  await expect(preview.getByRole('row', { name: /20–25 min/ })).toContainText('2%');

  await owner.getByRole('button', { name: 'Use defaults' }).click();
  await owner.getByTestId('save-discounts').click();
  await expect(owner.getByText('Saved. New orders use this policy')).toBeVisible();
  await expect(owner.getByTestId('policy-summary')).toContainText('Served within 15 min');
  await owner.context().close();
});
