import { APIRequestContext, Browser, Page, expect, test } from '@playwright/test';

const PASSWORD = 'E2e-strong-pass1';
const unique = () => `${Date.now()}${Math.floor(Math.random() * 1000)}`;
const mobile = () => `9${String(Date.now()).slice(-6)}${Math.floor(100 + Math.random() * 899)}`;

async function registerOwner(request: APIRequestContext): Promise<{ email: string; name: string }> {
  const id = unique();
  const email = `e2e-p5-${id}@example.com`;
  const name = `P5 Cafe ${id}`;
  const res = await request.post('/api/v1/public/restaurants/register', {
    data: {
      restaurant_name: name,
      owner_name: 'Phase Five',
      email,
      mobile: mobile(),
      password: PASSWORD,
      address: '5 Table Street',
      city: 'Pune',
      state: 'Maharashtra',
      country: 'India',
      cuisines: ['Cafe & Bakery'],
      restaurant_type: 'Cafe',
    },
  });
  expect(res.status()).toBe(201);
  return { email, name };
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email or mobile number').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/restaurant-admin$/, { timeout: 15_000 });
}

async function setupFloor(page: Page): Promise<void> {
  await page.goto('/restaurant-admin/tables');
  await page.getByRole('tab', { name: 'Setup' }).click();
  await page.getByLabel('New section name').fill('Terrace');
  await page.getByRole('button', { name: 'Add section' }).click();
  await expect(page.getByLabel('Section name Terrace')).toBeVisible();
  for (const label of ['T1', 'T2']) {
    await page.getByLabel('New table name').fill(label);
    await page.getByRole('button', { name: 'Add table' }).click();
    await expect(page.getByLabel(`Name of table ${label}`)).toBeVisible();
  }
  await page.getByRole('tab', { name: 'Floor' }).click();
}

async function ownerPage(browser: Browser, email: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signIn(page, email);
  return page;
}

test('owner sets up the floor, seats guests (code + PIN), closes the table', async ({ page }) => {
  const { email } = await registerOwner(page.request);
  await signIn(page, email);
  await setupFloor(page);

  const t1 = page.getByRole('button', { name: /^Table T1, Available/ });
  await t1.click();
  await page.getByRole('menuitem', { name: 'Seat guests' }).click();
  const seat = page.getByRole('dialog');
  await seat.getByLabel('Party size').fill('3');
  await seat.getByLabel('Guest name (optional)').fill('Sharma');
  await seat.getByRole('button', { name: 'Seat guests' }).click();

  const codes = page.getByRole('dialog');
  await expect(codes.getByTestId('session-code')).toHaveText(/^[A-Z]{2}-\d{4}$/);
  await expect(codes.getByTestId('session-pin')).toHaveText(/^\d{4}$/);
  await codes.getByRole('button', { name: 'Done' }).click();

  await expect(page.getByRole('button', { name: /^Table T1, Occupied/ })).toContainText('Sharma');
  await page.getByRole('button', { name: /^Table T1, Occupied/ }).click();
  await page.getByRole('menuitem', { name: 'Guests left' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Close table' }).click();
  await page.getByRole('button', { name: /^Table T1, Cleaning/ }).click();
  await page.getByRole('menuitem', { name: 'Mark clean' }).click();
  await expect(page.getByRole('button', { name: /^Table T1, Available/ })).toBeVisible();
});

test('the floor board updates live on another device', async ({ browser, page }) => {
  test.setTimeout(60_000); // two signed-in devices + floor setup
  const { email } = await registerOwner(page.request);
  await signIn(page, email);
  await setupFloor(page);
  await expect(page.getByText('Live — updates from every device')).toBeVisible();

  const other = await ownerPage(browser, email); // second device, same restaurant
  await other.goto('/restaurant-admin/tables');
  await expect(other.getByText('Live — updates from every device')).toBeVisible();
  await expect(other.getByRole('button', { name: /^Table T2, Available/ })).toBeVisible();

  await page.getByRole('button', { name: /^Table T2, Available/ }).click();
  await page.getByRole('menuitem', { name: 'Mark reserved' }).click();

  // No reload on the other device.
  await expect(other.getByRole('button', { name: /^Table T2, Reserved/ })).toBeVisible();
  await other.context().close();
});

test('owner adds a waiter who signs in with a mobile code and sees the floor', async ({ browser, page }) => {
  test.setTimeout(60_000); // several sign-ins and pages
  const { email, name } = await registerOwner(page.request);
  await signIn(page, email);
  await setupFloor(page);

  const waiterMobile = mobile();
  await page.goto('/restaurant-admin/employees');
  await page.getByRole('button', { name: 'Add employee' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Full name').fill('Ravi Waiter');
  await dialog.getByLabel('Mobile number').fill(waiterMobile);
  await dialog.getByLabel('Role').click();
  await page.getByRole('option', { name: 'Waiter' }).click();
  await dialog.getByRole('button', { name: 'Add employee' }).click();
  await expect(page.getByRole('row', { name: /Ravi Waiter/ })).toContainText('Waiter');

  const waiter = await (await browser.newContext()).newPage();
  await waiter.goto('/login');
  await waiter.getByRole('tab', { name: 'Mobile code' }).click();
  await waiter.getByLabel('Mobile number', { exact: true }).fill(waiterMobile);
  await waiter.getByRole('button', { name: 'Send code' }).click();
  const code = (await waiter.getByRole('note').locator('b').textContent())!.trim();
  await waiter.getByLabel('6-digit code').fill(code);
  await waiter.getByRole('button', { name: /Verify/ }).click();
  await expect(waiter).toHaveURL(/\/restaurant-admin$/);
  await expect(waiter.getByRole('heading', { level: 1 })).toHaveText(name);

  await waiter.goto('/restaurant-admin/tables');
  await expect(waiter.getByRole('button', { name: /^Table T1, Available/ })).toBeVisible();
  await expect(waiter.getByRole('tab', { name: 'Setup' })).toHaveCount(0); // waiters cannot configure
  await waiter.context().close();
});
