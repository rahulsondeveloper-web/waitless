import { APIRequestContext, Browser, Page, expect, test } from '@playwright/test';

/** Phase 9: inventory items & stock changes, alerts → purchase order → receive → pay, recipes deducted on Accept. */

const OWNER = 'e2e.owner@urbanbites.example.com';
const OWNER_PASSWORD = 'Demo-pass-123';

async function api(request: APIRequestContext): Promise<{ headers: Record<string, string>; branchId: string }> {
  const r = await request.post('/api/v1/auth/login', { data: { identifier: OWNER, password: OWNER_PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await r.json()).access_token}` };
  const me = await (await request.get('/api/v1/restaurant/me', { headers })).json();
  const branch = me.branches.find((b: { is_primary: boolean }) => b.is_primary) ?? me.branches[0];
  return { headers, branchId: branch.id };
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

test('owner adds an item, records opening stock and wastage with a reason, and sees the history', async ({ browser }) => {
  const name = `Saffron ${Date.now()}`;
  const page = await ownerPage(browser, '/restaurant-admin/inventory');
  await expect(page.getByTestId('stock-table')).toContainText('Flour');

  await page.getByTestId('new-inventory-item').click();
  const dialog = page.getByRole('dialog');
  await dialog.getByTestId('item-name').fill(name);
  await dialog.getByTestId('item-unit').selectOption('g');
  await dialog.getByTestId('item-price').fill('2');
  await dialog.getByTestId('item-reorder').fill('20');
  await dialog.getByTestId('save-item').click();
  await expect(dialog).toBeHidden();

  const row = page.getByTestId('stock-row').filter({ hasText: name });
  await expect(row).toContainText('Out of stock');
  await row.getByTestId('stock-change').click();
  const move = page.getByRole('dialog');
  await expect(move.getByTestId('move-type')).toHaveValue('opening');
  await move.getByTestId('move-qty').fill('50');
  await move.getByTestId('save-move').click();
  await expect(row.getByTestId('stock-on-hand')).toHaveText('50 g');

  await row.getByTestId('stock-change').click();
  await move.getByTestId('move-type').selectOption('wastage');
  await move.getByTestId('move-qty').fill('35');
  await expect(move.getByTestId('save-move')).toBeDisabled(); // a reason is required
  await move.getByTestId('move-reason').fill('Got damp');
  await move.getByTestId('save-move').click();
  await expect(row.getByTestId('stock-on-hand')).toHaveText('15 g');
  await expect(row).toContainText('Low');

  await row.getByRole('button', { name: `More for ${name}` }).click();
  await page.getByRole('menuitem', { name: 'History' }).click();
  const history = page.getByRole('dialog').getByTestId('history');
  await expect(history).toContainText('Wastage');
  await expect(history).toContainText('Got damp');
  await expect(history).toContainText('Opening stock');
  await page.context().close();
});

test('low stock alert → purchase order → receive → stock up → pay supplier', async ({ page: seedPage, browser }) => {
  test.setTimeout(60_000);
  // Its own supplier and low item, so parallel runs never restock each other's alert.
  const { headers, branchId } = await api(seedPage.request);
  const stamp = Date.now();
  const supplierName = `Spice Route ${stamp}`;
  const supplier = await (await seedPage.request.post('/api/v1/restaurant/suppliers', { headers, data: { name: supplierName } })).json();
  const item = await (
    await seedPage.request.post('/api/v1/restaurant/inventory/items', {
      headers,
      data: { name: `Cardamom ${stamp}`, unit: 'kg', reorder_level: '2', purchase_price: '2400', supplier_id: supplier.id },
    })
  ).json();
  await seedPage.request.post('/api/v1/restaurant/inventory/movements', {
    headers,
    data: { branch_id: branchId, item_id: item.id, type: 'opening', quantity: '0.5', reason: '' },
  });

  const page = await ownerPage(browser, '/restaurant-admin/inventory');
  await page.getByRole('tab', { name: /Alerts/ }).click();
  const group = page.getByTestId('alert-group').filter({ hasText: supplierName });
  await expect(group).toContainText(item.name);
  await expect(group).toContainText('3.5 kg'); // suggested: up to twice the reorder level
  await group.getByTestId('order-suggested').click();
  const po = page.getByRole('dialog');
  await expect(po.getByTestId('po-supplier')).toHaveValue(/.+/);
  await expect(po.getByTestId('po-total')).not.toHaveText('Total ₹0');
  await po.getByTestId('po-save-ordered').click();
  await expect(po).toBeHidden();

  await page.goto('/restaurant-admin/purchases');
  const row = page.getByTestId('purchase-row').filter({ hasText: supplierName });
  await expect(row).toBeVisible();
  const number = (await row.locator('.row__lead').textContent())!.trim();
  await row.getByTestId('receive-purchase').click();
  const rc = page.getByRole('dialog');
  await expect(rc.getByTestId('rc-qty')).toHaveValue('3.5');
  await rc.getByTestId('rc-save').click();
  await expect(page.getByText(`${number} received — stock updated.`)).toBeVisible();
  const stock = await (await seedPage.request.get(`/api/v1/restaurant/inventory/stock?branch_id=${branchId}`, { headers })).json();
  expect(stock.find((r: { item_id: string }) => r.item_id === item.id).on_hand).toBe('4.000');

  await page.getByRole('tab', { name: 'Unpaid' }).click();
  const unpaid = page.getByTestId('purchase-row').filter({ hasText: number });
  await expect(unpaid).toContainText('Unpaid');
  await unpaid.getByTestId('pay-purchase').click();
  await page.getByRole('dialog').getByTestId('pay-save').click();
  await expect(page.getByTestId('purchase-row').filter({ hasText: number })).toHaveCount(0); // no longer unpaid
  await page.getByRole('tab', { name: 'All' }).click();
  await expect(page.getByTestId('purchase-row').filter({ hasText: number })).toContainText('Paid');
  await page.context().close();
});

test('recipe set on the Menu page is deducted once when the kitchen accepts, and put back on cancel', async ({
  page,
  browser,
}) => {
  test.setTimeout(60_000);
  const { headers, branchId } = await api(page.request);
  const stamp = Date.now();
  const item = await (
    await page.request.post('/api/v1/restaurant/inventory/items', {
      headers,
      data: { name: `Truffle ${stamp}`, unit: 'kg', purchase_price: '1000' },
    })
  ).json();
  await page.request.post('/api/v1/restaurant/inventory/movements', {
    headers,
    data: { branch_id: branchId, item_id: item.id, type: 'opening', quantity: '1', reason: '' },
  });
  const menu = await (await page.request.get('/api/v1/restaurant/menu', { headers })).json();
  const dishName = `Truffle Toast ${stamp}`;
  const dish = await (
    await page.request.post('/api/v1/restaurant/menu/items', {
      headers,
      data: { category_id: menu.categories[0].id, name: dishName, base_price: '450' },
    })
  ).json();

  // Recipe through the UI: 250 g of an item stocked in kg.
  const owner = await ownerPage(browser, '/restaurant-admin/menu');
  await owner.locator('li', { hasText: dishName }).getByTestId('open-recipe').click();
  const dialog = owner.getByRole('dialog');
  await dialog.getByTestId('recipe-item').selectOption({ label: item.name });
  await dialog.getByTestId('recipe-qty').fill('250');
  await dialog.getByTestId('save-recipe').click();
  await expect(owner.getByText('Recipe saved — 1 ingredients.')).toBeVisible();
  await owner.context().close();

  const onHand = async () => {
    const rows = await (await page.request.get(`/api/v1/restaurant/inventory/stock?branch_id=${branchId}`, { headers })).json();
    return rows.find((r: { item_id: string }) => r.item_id === item.id).on_hand;
  };
  const board = await (await page.request.get(`/api/v1/restaurant/tables/board?branch_id=${branchId}`, { headers })).json();
  let session: { id: string } | null = null;
  let tableId = '';
  for (const t of board.tables.filter((x: { status: string }) => x.status === 'available').reverse()) {
    const r = await page.request.post('/api/v1/restaurant/table-sessions', { headers, data: { table_id: t.id, party_size: 2 } });
    if (r.status() === 201) {
      session = (await r.json()).session;
      tableId = t.id;
      break;
    }
  }
  expect(session).not.toBeNull();
  const order = await (
    await page.request.post('/api/v1/restaurant/orders', {
      headers,
      data: { table_session_id: session!.id, items: [{ menu_item_id: dish.id, quantity: 2 }] },
    })
  ).json();
  expect(await onHand()).toBe('1.000'); // placed: nothing taken yet

  expect((await page.request.post(`/api/v1/restaurant/orders/${order.id}/status`, { headers, data: { status: 'accepted' } })).ok()).toBe(true);
  expect(await onHand()).toBe('0.500');
  const again = await page.request.post(`/api/v1/restaurant/orders/${order.id}/status`, { headers, data: { status: 'accepted' } });
  expect(again.status()).toBe(409);
  expect(await onHand()).toBe('0.500');

  await page.request.post(`/api/v1/restaurant/orders/${order.id}/cancel`, { headers, data: { reason: 'Test' } });
  expect(await onHand()).toBe('1.000');
  await page.request.post(`/api/v1/restaurant/table-sessions/${session!.id}/close`, { headers });
  await page.request.patch(`/api/v1/restaurant/tables/${tableId}/status`, { headers, data: { status: 'available' } });
  await page.request.post(`/api/v1/restaurant/menu/items/${dish.id}/archive`, { headers });
});
