import { Browser, Page, expect, test } from '@playwright/test';

/** Phase 6: walk-in queue (live "table ready") and a paid reservation through the mock gateway. */

const SLUG = 'e2e-urban-bites';
const OWNER = 'e2e.owner@urbanbites.example.com';
const OWNER_PASSWORD = 'Demo-pass-123';
const unique = () => `${Date.now()}${Math.floor(Math.random() * 1000)}`;
const mobile = () => `9${String(Date.now()).slice(-6)}${Math.floor(100 + Math.random() * 899)}`;

async function guestSignIn(page: Page, name: string): Promise<void> {
  await page.getByRole('tab', { name: 'Mobile code' }).click();
  await page.getByLabel('Mobile number', { exact: true }).fill(mobile());
  await page.getByRole('button', { name: 'Send code' }).click();
  const code = (await page.locator('.auth__dev b').textContent())!.trim();
  await page.getByLabel('6-digit code').fill(code);
  await page.getByLabel('Your name (first time only)').fill(name);
  await page.getByRole('button', { name: /Verify/ }).click();
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

function tomorrowInIndia(): string {
  const d = new Date(Date.now() + 86_400_000);
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
}

test('guest joins the queue; staff says "table ready" and seats them — live', async ({ page, browser, request }) => {
  test.setTimeout(60_000); // guest + staff devices
  const name = `Queue Guest ${unique()}`;
  // A party of 2 already waits (added by staff), so the 2-seat tables are theirs: our guest gets a token
  // instead of being seated straight away.
  const login = await request.post('/api/v1/auth/login', { data: { identifier: OWNER, password: OWNER_PASSWORD } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const me = await (await request.get('/api/v1/restaurant/me', { headers })).json();
  const branch = me.branches.find((b: { is_primary: boolean }) => b.is_primary) ?? me.branches[0];
  const ahead = await (
    await request.post('/api/v1/restaurant/queue', { headers, data: { branch_id: branch.id, party_size: 2, guest_name: `Ahead ${unique()}` } })
  ).json();

  await page.goto(`/r/${SLUG}/queue`);
  await page.getByRole('button', { name: 'Sign in with your mobile to join' }).click();
  await guestSignIn(page, name);
  await expect(page).toHaveURL(new RegExp(`/r/${SLUG}/queue`), { timeout: 15_000 });

  await page.getByTestId('queue-party').fill('2');
  await page.getByRole('button', { name: /Continue|Get my token/ }).click();
  const token = page.getByTestId('queue-token');
  await expect(token).toContainText(/A-\d{3}/);
  await expect(token).toContainText('Waiting');
  await request.post(`/api/v1/restaurant/queue/${ahead.id}/cancel`, { headers });

  const staff = await ownerPage(browser, '/restaurant-admin/queue');
  const row = staff.getByTestId('queue-row').filter({ hasText: name });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: 'Table ready' }).click();
  await staff.getByRole('menuitem', { name: 'Notify (no table held)' }).click();

  // The guest's page updates by itself (Socket.IO).
  await expect(page.getByRole('alert')).toContainText('Your table is ready', { timeout: 15_000 });

  await row.getByTestId('q-seat').click();
  await staff.getByRole('menuitem').first().click();
  const codes = staff.getByRole('dialog');
  await expect(codes.getByTestId('session-code')).toHaveText(/^[A-Z]{2}-\d{4}$/);
  await codes.getByRole('button', { name: 'Done' }).click();
  await expect(token).toContainText('Enjoy your meal', { timeout: 15_000 });
  await staff.context().close();
});

test('paid booking: policy → slot → mock payment (webhook) → staff confirms arrival', async ({ page, browser }) => {
  test.setTimeout(60_000); // guest + staff devices
  // Owner turns on paid bookings.
  const staff = await ownerPage(browser, '/restaurant-admin/reservations');
  await staff.getByRole('tab', { name: 'Booking policy' }).click();
  const paid = staff.getByTestId('paid-toggle').getByRole('switch');
  if ((await paid.getAttribute('aria-checked')) !== 'true') await paid.click();
  await staff.getByLabel('Booking fee (₹)').fill('200');
  await staff.getByTestId('save-policy').click();
  await expect(staff.getByText('Booking policy saved.')).toBeVisible();

  // Guest books a paid table for tomorrow 13:00.
  const name = `Paid Guest ${unique()}`;
  await page.goto(`/r/${SLUG}/reservations`);
  await page.getByRole('button', { name: 'Sign in with your mobile to book' }).click();
  await guestSignIn(page, name);
  await expect(page).toHaveURL(new RegExp(`/r/${SLUG}/reservations$`), { timeout: 15_000 });
  await expect(page.getByTestId('signed-in-as')).toContainText(name); // who the booking is for, always visible
  const day = tomorrowInIndia();
  await page.getByTestId('res-date').fill(day);
  await page.getByRole('option', { name: '13:00' }).click();
  await page.getByText('Paid booking · ₹200').click();
  await page.getByTestId('res-confirm').click();

  await expect(page).toHaveURL(/\/pay\/mock\/mock_order_/);
  await expect(page.getByText('₹200').first()).toBeVisible();
  await page.getByTestId('pay-success').click();
  await expect(page.getByTestId('pay-result')).toContainText('your table is booked');
  await page.getByRole('link', { name: /Back to/ }).click();
  const mine = page.getByTestId('my-reservation').first();
  await expect(mine).toContainText('Confirmed');

  // The floor board shows the upcoming booking on its table before it turns "reserved".
  await staff.goto('/restaurant-admin/tables');
  await expect(staff.getByTestId('next-booking').filter({ hasText: name })).toContainText('Booked tomorrow 13:00');

  // Staff sees it on that day and confirms the arrival → table session code + PIN.
  await staff.goto('/restaurant-admin/reservations');
  await staff.getByTestId('admin-res-date').fill(day);
  await staff.getByTestId('admin-res-date').dispatchEvent('change');
  const row = staff.getByTestId('admin-reservation').filter({ hasText: name });
  await expect(row).toContainText('Paid ₹200');
  await row.getByTestId('arrive').click();
  await staff.getByRole('menuitem').first().click();
  await expect(staff.getByRole('dialog').getByTestId('session-pin')).toHaveText(/^\d{4}$/);
  await staff.getByRole('dialog').getByRole('button', { name: 'Done' }).click();
  await expect(row).toContainText('Arrived');
  await staff.context().close();
});
