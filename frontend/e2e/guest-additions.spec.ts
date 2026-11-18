import { APIRequestContext, Browser, Page, expect, test } from '@playwright/test';

/** Post-launch additions: table QR codes, guest names, Finish popup → checkout (restaurant UPI), category photos, page access. */

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

test('the menu is laid out in the template spreads with category photos', async ({ page }) => {
  await page.goto(`/r/${SLUG}/menu`);
  const spread = page.getByTestId('menu-spread').first();
  await expect(spread).toBeVisible();
  await expect(spread.getByTestId('category-photo').first()).toHaveAttribute('src', /.+/);
  await expect(spread.getByTestId('menu-item').first()).toBeVisible();
  await expect(page.getByTestId('category-nav')).toBeVisible();
});

test('a guest scans the table QR, opens the table with their name and orders under it', async ({ page, browser }, info) => {
  test.setTimeout(90_000);
  const { headers, branchId } = await api(page.request);
  await page.request.put('/api/v1/restaurant/table-qr/self-seating', { headers, data: { enabled: true } });
  const board = await (await page.request.get(`/api/v1/restaurant/tables/board?branch_id=${branchId}`, { headers })).json();
  // A truly free table (no session left behind), a different one per project so parallel runs don't collide.
  const frees = board.tables.filter((x: { status: string; session: unknown }) => x.status === 'available' && !x.session).reverse();
  const free = frees[info.project.name === 'mobile' ? 1 : 0];
  expect(free).toBeTruthy();
  const sheet = await (await page.request.get(`/api/v1/restaurant/table-qr?branch_id=${branchId}`, { headers })).json();
  const card = sheet.tables.find((t: { table_id: string }) => t.table_id === free.id);

  // Staff see one printable QR per table.
  const staff = await ownerPage(browser, '/restaurant-admin/tables');
  await staff.getByTestId('table-qr-link').click();
  await expect(staff.getByTestId('qr-card').first()).toBeVisible();
  await expect(staff.getByTestId('qr-card').filter({ hasText: `Table ${free.label}` }).locator('img')).toBeVisible();
  await staff.context().close();

  // The guest scans it.
  await page.goto(card.path);
  await expect(page.getByTestId('qr-table')).toHaveText(`Table ${free.label}`);
  await page.getByTestId('qr-name').fill('Kabir');
  await page.getByTestId('qr-start').click();
  await expect(page.getByTestId('qr-pin')).toHaveText(/^\d{4}$/);
  const code = (await page.getByTestId('qr-code').textContent())!.trim();
  await page.getByTestId('qr-menu').click();
  await page.getByRole('button', { name: /^Add / }).first().click();
  await page.getByTestId('add-to-cart').click();
  await page.getByTestId('cart-bar').click();
  await expect(page.getByTestId('cart-who')).toContainText("Kabir's order");
  await page.getByTestId('place-order').click();
  await expect(page.getByTestId('table-view')).toContainText(code);
  await expect(page.getByTestId('table-order').first().getByTestId('ordered-by')).toHaveText('Kabir');

  // Kitchen ticket carries the name.
  const kitchen = await ownerPage(browser, '/restaurant-admin/kitchen');
  await expect(kitchen.getByTestId('ticket').filter({ hasText: `Table ${free.label}` })).toContainText('Kabir');
  await kitchen.context().close();

  // Clean up: the guest cancels (before the kitchen accepts), staff close the table and free it.
  page.once('dialog', (d) => d.accept());
  await page.getByTestId('table-order').first().getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByTestId('table-order').first()).toContainText('Cancelled');
  const after = await (await page.request.get(`/api/v1/restaurant/tables/board?branch_id=${branchId}`, { headers })).json();
  const sid = after.tables.find((t: { id: string }) => t.id === free.id)?.session?.id;
  if (sid) expect((await page.request.post(`/api/v1/restaurant/table-sessions/${sid}/close`, { headers })).ok()).toBeTruthy();
  await page.request.patch(`/api/v1/restaurant/tables/${free.id}/status`, { headers, data: { status: 'available' } });
});

test("Finish shows the bill in a popup; the guest pays the restaurant's UPI ID and staff confirm it", async ({ page, browser }, info) => {
  test.setTimeout(120_000);
  const { headers, branchId } = await api(page.request);
  const settings = await (await page.request.get('/api/v1/restaurant/billing-settings', { headers })).json();
  await page.request.put('/api/v1/restaurant/billing-settings', {
    headers,
    data: { ...settings, upi_id: 'urbanbites@okaxis', upi_payee_name: 'Urban Bites' },
  });
  try {
    // Seat and serve an order.
    const board = await (await page.request.get(`/api/v1/restaurant/tables/board?branch_id=${branchId}`, { headers })).json();
    let seated: { session: { id: string; public_code: string }; pin: string; label: string; tableId: string } | null = null;
    // Free tables from the end, skipping the two the QR test uses; a table taken meanwhile returns 409 and is skipped.
    const frees = board.tables.filter((x: { status: string; session: unknown }) => x.status === 'available' && !x.session).reverse();
    for (const t of frees.slice(2)) {
      const r = await page.request.post('/api/v1/restaurant/table-sessions', { headers, data: { table_id: t.id, party_size: 2, guest_name: 'UPI Guest' } });
      if (r.status() !== 201) continue;
      const s = await r.json();
      seated = { session: s.session, pin: s.pin, label: t.label, tableId: t.id };
      break;
    }
    expect(seated).toBeTruthy();
    const menu = await (await page.request.get('/api/v1/restaurant/menu', { headers })).json();
    const dish = (menu.items as Dish[]).find((i) => i.is_available && !i.is_archived && !i.variants.length && !i.availability.length)!;
    const order = await (
      await page.request.post('/api/v1/restaurant/orders', {
        headers,
        data: { table_session_id: seated!.session.id, items: [{ menu_item_id: dish.id, quantity: 1 }] },
      })
    ).json();
    for (const st of ['accepted', 'preparing', 'ready', 'served']) {
      await page.request.post(`/api/v1/restaurant/orders/${order.id}/status`, { headers, data: { status: st } });
    }

    await page.goto(`/r/${SLUG}/session`);
    await page.getByTestId('join-code').fill(seated!.session.public_code);
    await page.getByTestId('join-name').fill('Meera');
    await page.getByTestId('join-pin').fill(seated!.pin);
    await page.getByRole('button', { name: 'Open my table' }).click();
    await page.getByTestId('finish').click();
    await page.getByTestId('finish-confirm').click();
    await page.getByTestId('popup-pay-now').click();

    const upi = page.getByTestId('pay-upi-direct');
    await expect(upi.getByTestId('upi-id')).toHaveText('urbanbites@okaxis');
    await expect(upi.getByTestId('upi-qr')).toHaveAttribute('src', /^data:image\/png/);
    await upi.getByTestId('upi-ref').fill('412345678901');
    await upi.getByTestId('upi-paid').click();
    await expect(page.getByTestId('checkout-waiting')).toBeVisible();

    const staff = await ownerPage(browser, '/restaurant-admin/billing');
    await staff.getByTestId('billing-table').filter({ hasText: `Table ${seated!.label}` }).click();
    await expect(staff.getByTestId('upi-claim')).toBeVisible();
    await staff.getByTestId('upi-confirm').click();
    await expect(page.getByTestId('checkout-paid')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId('download-invoice')).toBeVisible();
    await staff.getByTestId('close-table').click();
    await expect(staff.getByText(`Table ${seated!.label} closed`)).toBeVisible();
    await staff.context().close();
    await page.request.patch(`/api/v1/restaurant/tables/${seated!.tableId}/status`, { headers, data: { status: 'available' } });
  } finally {
    await page.request.put('/api/v1/restaurant/billing-settings', { headers, data: { ...settings, upi_id: '', upi_payee_name: '' } });
  }
});

test('the owner sees which pages each role can open and can customise a built-in role', async ({ browser }) => {
  const page = await ownerPage(browser, '/restaurant-admin/employees');
  await page.getByRole('tab', { name: /Roles/ }).click();
  await expect(page.getByTestId('role-pages-summary').first()).toContainText('Pages:');
  await page.getByRole('button', { name: /Customise a copy of/ }).first().click();
  const dlg = page.getByRole('dialog');
  await expect(dlg.getByTestId('role-pages')).toBeVisible();
  await expect(dlg.getByTestId('page-kitchen')).toBeVisible();
  await dlg.getByRole('button', { name: 'Cancel' }).click();
  await page.context().close();
});
