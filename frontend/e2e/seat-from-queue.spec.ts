import { Browser, Page, expect, test } from '@playwright/test';

/** Home page: "Location" opens a map; "Join the queue" asks for guests and seats them at once when a table suits. */

const SLUG = 'e2e-urban-bites';
const OWNER = 'e2e.owner@urbanbites.example.com';
const OWNER_PASSWORD = 'Demo-pass-123';
const mobile = () => `9${String(Date.now()).slice(-6)}${Math.floor(100 + Math.random() * 899)}`;

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

test('Location shows the restaurant on a map', async ({ page }) => {
  await page.goto(`/r/${SLUG}`);
  await page.getByTestId('location-button').click();
  const popup = page.getByTestId('location-popup');
  await expect(popup).toBeVisible();
  await expect(popup.locator('.leaflet-container')).toBeVisible({ timeout: 15_000 });
  await expect(popup.getByTestId('location-directions')).toHaveAttribute('href', /openstreetmap\.org\/directions/);
  await page.keyboard.press('Escape');
  await expect(popup).toHaveCount(0);
});

test('a party of 5 joins the queue while tables are free: seated at once, the waiter is alerted', async ({ page, browser, request }) => {
  test.setTimeout(90_000);
  const name = `Seat Now ${Date.now() % 1_000_000}`;
  await page.goto(`/r/${SLUG}`);
  await page.getByTestId('join-queue').click();
  const ask = page.getByTestId('join-queue-popup');
  await expect(ask).toContainText('How many guests?');
  await ask.getByRole('button', { name: 'One guest more' }).click();
  await ask.getByRole('button', { name: 'One guest more' }).click();
  await ask.getByRole('button', { name: 'One guest more' }).click();
  await expect(ask.getByTestId('jq-party')).toHaveValue('5');

  // Not signed in yet: sign in with the mobile, back on the queue page with 5 guests filled in.
  await ask.getByTestId('jq-sign-in').click();
  await page.getByRole('tab', { name: 'Mobile code' }).click();
  await page.getByLabel('Mobile number', { exact: true }).fill(mobile());
  await page.getByRole('button', { name: 'Send code' }).click();
  const code = (await page.locator('.auth__dev b').textContent())!.trim();
  await page.getByLabel('6-digit code').fill(code);
  await page.getByLabel('Your name (first time only)').fill(name);
  await page.getByRole('button', { name: /Verify/ }).click();
  await expect(page).toHaveURL(new RegExp(`/r/${SLUG}/queue\\?party=5`), { timeout: 15_000 });
  await expect(page.getByTestId('queue-party')).toHaveValue('5');

  const staff = await ownerPage(browser, '/restaurant-admin/tables');
  let orderId = '';
  try {
    await page.getByRole('button', { name: /Continue|Get my token/ }).click();
    const seated = page.getByTestId('queue-seated');
    await expect(seated.getByTestId('seated-table')).toContainText(/Table \S+/, { timeout: 15_000 });
    orderId = (await seated.getByTestId('seated-code').textContent({ timeout: 10_000 }))!.trim();
    await expect(seated.getByTestId('seated-pin')).toHaveText(/^\d{4}$/);

    // Waiters see who sat down and whether to bring chairs; Done clears it.
    const alert = staff.getByTestId('service-call').filter({ hasText: name });
    await expect(alert).toContainText('New guests seated', { timeout: 15_000 });
    await expect(alert.getByTestId('service-note')).toContainText('Party of 5');
    await alert.getByTestId('service-done').click({ timeout: 10_000 });
    await expect(alert).toHaveCount(0);

    // The guest's phone orders for that table now.
    await seated.getByTestId('seated-menu').click({ timeout: 10_000 });
    await expect(page).toHaveURL(new RegExp(`/r/${SLUG}/menu`));
    await expect(page.getByTestId('call-waiter')).toBeVisible();
  } finally {
    // Free the table again for other tests.
    const login = await request.post('/api/v1/auth/login', { data: { identifier: OWNER, password: OWNER_PASSWORD } });
    const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
    const me = await (await request.get('/api/v1/restaurant/me', { headers })).json();
    const branch = me.branches.find((b: { is_primary: boolean }) => b.is_primary) ?? me.branches[0];
    const board = await (await request.get(`/api/v1/restaurant/tables/board?branch_id=${branch.id}`, { headers })).json();
    const t = board.tables.find((x: { session: { public_code: string } | null }) => orderId && x.session?.public_code === orderId);
    if (t) {
      await request.post(`/api/v1/restaurant/table-sessions/${t.session.id}/close`, { headers });
      await request.patch(`/api/v1/restaurant/tables/${t.id}/status`, { headers, data: { status: 'available' } });
    }
    await staff.context().close();
  }
});
